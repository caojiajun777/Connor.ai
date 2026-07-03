"""Application configuration primitives."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="CONNOR_", env_file=".env", extra="ignore")

    database_url: str = Field(default="sqlite:///./connor_dev.db")
    artifact_root: str = Field(default="artifacts")
    artifact_inline_max_bytes: int = Field(default=64_000, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
