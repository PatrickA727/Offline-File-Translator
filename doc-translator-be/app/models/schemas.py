from pydantic import BaseModel
from enum import Enum
from datetime import datetime


class Language(str, Enum):
    ENGLISH = "en"
    CHINESE = "zh"
    JAPANESE = "ja"
    INDONESIAN = "id"

class TextNode(BaseModel):
    """
    A unit of translatable text extracted from a document.
    Carries enough metadata to write the translation back
    to the correct location.
    """
    id: int
    text: str
    location: dict

class FileStatus(str, Enum):
    PENDING = "pending"
    TRANSLATING = "translating"
    COMPLETED = "completed"
    FAILED = "failed"
 
 
class BatchFileResult(BaseModel):
    original_filename: str
    translated_filename: str | None = None
    status: FileStatus = FileStatus.PENDING
    error: str | None = None
 
 
class BatchJobStatus(BaseModel):
    job_id: str
    status: str
    source_lang: str
    target_lang: str
    total_files: int
    completed_files: int
    failed_files: int
    files: list[BatchFileResult]
    created_at: datetime
    completed_at: datetime | None = None
