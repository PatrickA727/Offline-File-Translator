from pathlib import Path
from app.services.translator import TranslationService


async def translate_filename(
    original_name: str,
    source_lang: str,
    target_lang: str,
    translator: TranslationService
) -> str:
    
    path = Path(original_name)
    stem = path.stem
    suffix = path.suffix

    translated_stem = await translator.translate_text(stem, source_lang, target_lang)

    translated_stem = translated_stem.replace("/", "_").replace("\\", "_").replace(":", "_")

    translated_stem = translated_stem.rstrip(".")

    if not translated_stem or not translated_stem.strip():
        translated_stem = stem

    return f"{translated_stem}{suffix}"