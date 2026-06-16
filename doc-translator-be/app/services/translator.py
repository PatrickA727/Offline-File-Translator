import httpx
import logging
from app.config import get_settings
from app.models.schemas import TextNode

logger = logging.getLogger(__name__)

# Maps our internal codes to MTranServer's expected codes
LANG_CODE_MAP: dict[str, str] = {
    "en": "en",
    "zh": "zh-Hans",
    "ja": "ja",
    "id": "id",
}


def _mtran_code(lang: str) -> str:
    code = LANG_CODE_MAP.get(lang)
    if code is None:
        raise ValueError(f"Unsupported language code: '{lang}'. Supported: {list(LANG_CODE_MAP.keys())}")
    return code


class TranslationService:

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.mtranserver_url
        self.batch_size = self.settings.batch_size

    async def translate_text(
        self, text: str, source_lang: str, target_lang: str
    ) -> str:
        if not text or not text.strip():
            return text

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/translate",
                json={
                    "text": text,
                    "from": _mtran_code(source_lang),
                    "to": _mtran_code(target_lang),
                    "html": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("result", "")

    async def _translate_batch_request(
        self, texts: list[str], source_lang: str, target_lang: str
    ) -> list[str]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/translate/batch",
                json={
                    "texts": texts,
                    "from": _mtran_code(source_lang),
                    "to": _mtran_code(target_lang),
                    "html": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])

    async def translate_batch(
        self, texts: list[str], source_lang: str, target_lang: str
    ) -> list[str]:
        if not texts:
            return []

        results: list[str] = [""] * len(texts)

        batch_texts: list[str] = []
        batch_indices: list[int] = []

        for i, text in enumerate(texts):
            if text and text.strip():
                batch_texts.append(text)
                batch_indices.append(i)
            else:
                results[i] = text

        for chunk_start in range(0, len(batch_texts), self.batch_size):
            chunk_end = chunk_start + self.batch_size
            chunk = batch_texts[chunk_start:chunk_end]
            chunk_indices = batch_indices[chunk_start:chunk_end]

            try:
                translated_chunk = await self._translate_batch_request(
                    chunk, source_lang, target_lang
                )

                for idx, translated in zip(chunk_indices, translated_chunk):
                    results[idx] = translated

            except Exception as e:
                logger.error(f"Batch translation failed for chunk starting at {chunk_start}: {e}")
                for idx, original in zip(chunk_indices, chunk):
                    results[idx] = original

        return results

    async def translate_nodes(
        self, nodes: list[TextNode], source_lang: str, target_lang: str
    ) -> dict[int, str]:
        texts = [node.text for node in nodes]
        translated = await self.translate_batch(texts, source_lang, target_lang)
        return {node.id: trans for node, trans in zip(nodes, translated)}