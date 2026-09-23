from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_ignore_empty=True, extra="ignore"
    )

    ai_mock: bool = True
    storage_dir: Path = BACKEND_DIR / "storage"
    frontend_origin: str = "http://localhost:5173"


settings = Settings()
