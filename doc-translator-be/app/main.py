import os
import uuid
import shutil
import asyncio
import logging
from pathlib import Path
from typing import List
from datetime import datetime
from contextlib import asynccontextmanager
 
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, APIRouter
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
 
from app.config import get_settings
from app.models.schemas import (
    Language, BatchJobStatus, BatchFileResult, FileStatus,
)
from app.services.translator import TranslationService
from app.handlers.docx_handler import DocxHandler
from app.handlers.xlsx_handler import XlsxHandler
from app.utils.filename import translate_filename

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
 
settings = get_settings()
 
# In-memory job store — sufficient for small-scale private deployment
batch_jobs: dict[str, BatchJobStatus] = {}
 
 
@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.temp_dir, exist_ok=True)
    yield
 
 
app = FastAPI(
    title="Document Translator",
    description="Translate .docx and .xlsx files while preserving formatting",
    version="0.1.0",
    lifespan=lifespan,
)
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
 
SUPPORTED_EXTENSIONS = {".docx", ".xlsx"}
 
 
def _get_handler(file_path: str, suffix: str):
    if suffix == ".docx":
        return DocxHandler(file_path)
    elif suffix == ".xlsx":
        return XlsxHandler(file_path)
    else:
        raise ValueError(f"No handler for {suffix}")
 
 
async def _translate_single_file(
    input_path: Path,
    original_name: str,
    source_lang: str,
    target_lang: str,
    output_dir: Path,
    translator: TranslationService,
) -> str:
    suffix = Path(original_name).suffix.lower()
    handler = _get_handler(str(input_path), suffix)
 
    nodes = handler.extract_nodes()
    translations = await translator.translate_nodes(nodes, source_lang, target_lang)
    handler.apply_translations(translations)
 
    translated_name = await translate_filename(
        original_name, source_lang, target_lang, translator
    )
 
    output_path = output_dir / translated_name
    handler.save(str(output_path))
    return translated_name
 
 
async def _process_batch(job_id: str, job_dir: Path, source_lang: str, target_lang: str):
    job = batch_jobs[job_id]
    translator = TranslationService()
    output_dir = job_dir / "output"
    os.makedirs(output_dir, exist_ok=True)
 
    for file_result in job.files:
        try:
            file_result.status = FileStatus.TRANSLATING
            original_name = file_result.original_filename
            suffix = Path(original_name).suffix.lower()
            input_path = job_dir / "input" / original_name
 
            translated_name = await _translate_single_file(
                input_path, original_name, source_lang, target_lang,
                output_dir, translator,
            )
 
            file_result.translated_filename = translated_name
            file_result.status = FileStatus.COMPLETED
            job.completed_files += 1
            logger.info(f"Batch {job_id}: translated {original_name} → {translated_name}")
 
        except Exception as e:
            file_result.status = FileStatus.FAILED
            file_result.error = str(e)
            job.failed_files += 1
            logger.exception(f"Batch {job_id}: failed to translate {original_name}")
 
    successful = [f for f in job.files if f.status == FileStatus.COMPLETED]
    if successful:
        zip_path = job_dir / "translated_files.zip"
        import zipfile
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_result in successful:
                file_path = output_dir / file_result.translated_filename
                zf.write(file_path, file_result.translated_filename)
 
    if job.failed_files == 0:
        job.status = "completed"
    elif job.completed_files == 0:
        job.status = "failed"
    else:
        job.status = "completed_with_errors"
 
    job.completed_at = datetime.now()
    logger.info(
        f"Batch {job_id}: finished — {job.completed_files} succeeded, "
        f"{job.failed_files} failed"
    )
 
 

router = APIRouter(prefix="/api")
 
@router.post("/translate")
async def translate_file(
    file: UploadFile = File(...),
    source_lang: Language = Form(...),
    target_lang: Language = Form(...),
):
    if source_lang == target_lang:
        raise HTTPException(400, "Source and target languages must be different")
 
    original_name = file.filename or "document"
    suffix = Path(original_name).suffix.lower()
 
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Unsupported file type '{suffix}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}",
        )
 
    job_id = uuid.uuid4().hex[:12]
    job_dir = Path(settings.temp_dir) / job_id
    os.makedirs(job_dir, exist_ok=True)
 
    input_path = job_dir / f"input{suffix}"
    try:
        with open(input_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        raise HTTPException(500, f"Failed to save uploaded file: {e}")
 
    translator = TranslationService()
 
    try:
        translated_name = await _translate_single_file(
            input_path, original_name,
            source_lang.value, target_lang.value,
            job_dir, translator,
        )
 
        output_path = job_dir / translated_name
        logger.info(f"Job {job_id}: saved translated file as {translated_name}")
 
        return FileResponse(
            path=str(output_path),
            filename=translated_name,
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if suffix == ".docx"
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
 
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Job {job_id}: translation failed")
        raise HTTPException(500, f"Translation failed: {e}")
 
 
@router.post("/translate/batch")
async def translate_batch(
    files: List[UploadFile] = File(...),
    source_lang: Language = Form(...),
    target_lang: Language = Form(...),
):
    if source_lang == target_lang:
        raise HTTPException(400, "Source and target languages must be different")
 
    if not files:
        raise HTTPException(400, "No files provided")
 
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                400,
                f"Unsupported file '{f.filename}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}",
            )
 
    job_id = uuid.uuid4().hex[:12]
    job_dir = Path(settings.temp_dir) / f"batch_{job_id}"
    input_dir = job_dir / "input"
    os.makedirs(input_dir, exist_ok=True)
 
    file_results: list[BatchFileResult] = []
    for f in files:
        original_name = f.filename or "document"
        save_path = input_dir / original_name
        try:
            with open(save_path, "wb") as out:
                content = await f.read()
                out.write(content)
            file_results.append(BatchFileResult(original_filename=original_name))
        except Exception as e:
            file_results.append(BatchFileResult(
                original_filename=original_name,
                status=FileStatus.FAILED,
                error=f"Failed to save: {e}",
            ))
 
    job = BatchJobStatus(
        job_id=job_id,
        status="processing",
        source_lang=source_lang.value,
        target_lang=target_lang.value,
        total_files=len(files),
        completed_files=0,
        failed_files=sum(1 for f in file_results if f.status == FileStatus.FAILED),
        files=file_results,
        created_at=datetime.now(),
    )
    batch_jobs[job_id] = job
 
    asyncio.create_task(_process_batch(job_id, job_dir, source_lang.value, target_lang.value))
 
    logger.info(f"Batch {job_id}: started with {len(files)} files")
    return {"job_id": job_id, "status": "processing", "total_files": len(files)}
 
 
@router.get("/translate/batch/{job_id}")
async def get_batch_status(job_id: str):
    job = batch_jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Batch job '{job_id}' not found")
    return job
 
 
@router.get("/translate/batch/{job_id}/download")
async def download_batch(job_id: str):
    job = batch_jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Batch job '{job_id}' not found")
 
    if job.status == "processing":
        raise HTTPException(409, "Job is still processing")
 
    zip_path = Path(settings.temp_dir) / f"batch_{job_id}" / "translated_files.zip"
    if not zip_path.exists():
        raise HTTPException(404, "No translated files available (all files may have failed)")
 
    return FileResponse(
        path=str(zip_path),
        filename="translated_files.zip",
        media_type="application/zip",
    )


app.include_router(router)

static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")