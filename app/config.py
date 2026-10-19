from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "Student Wellbeing API"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./burnout.db"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/v1/google/callback"
    google_token_encryption_key: str | None = None
    cron_secret: str | None = None
    public_base_url: str = "http://localhost:8000"
    cookie_secure: bool = False
    app_timezone: str = "Asia/Singapore"

    model_config = SettingsConfigDict(env_file=PROJECT_DIR / ".env", extra="ignore")


settings = Settings()
