"""CoOps Platform — 설정."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "coops"
    version: str = "0.1.0"
    environment: str = "development"
    llm_provider: str = "local"
    database_url: str = (
        "postgresql+asyncpg://dev:dev@postgres:5432/mediiot"
    )
    redis_url: str = "redis://redis:6379/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
