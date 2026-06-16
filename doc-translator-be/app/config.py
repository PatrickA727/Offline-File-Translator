from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    mtranserver_url: str = "http://localhost:8989"
    batch_size: int = 50
    temp_dir: str = "./temp"

    supported_languages: dict[str, str] = {
        "en": "English",
        "zh": "Chinese",
        "ja": "Japanese",
        "id": "Indonesian",
    }

    class Config:
        env_file = ".env"


@lru_cache  # Caches env
def get_settings() -> Settings:
    return Settings()
