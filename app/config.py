"""Application configuration primitives."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="CONNOR_", env_file=".env", extra="ignore")

    database_url: str = Field(default="postgresql+psycopg2://connor:connor_dev@localhost:5432/connor")
    artifact_root: str = Field(default="artifacts")
    artifact_inline_max_bytes: int = Field(default=64_000, gt=0)
    github_token: str | None = Field(default=None)
    huggingface_token: str | None = Field(default=None)
    tool_user_agent: str = Field(default="Connor.ai/0.1")
    sec_user_agent: str | None = Field(default=None)
    agent_timeout_seconds: int | None = Field(default=180, gt=0)
    # X / Twitter search via browser automation
    x_cookies_file: str = Field(default="x_cookies.json")
    # DeepSeek model provider
    deepseek_api_key: str | None = Field(default=None)
    deepseek_model: str = Field(default="deepseek-chat")
    deepseek_base_url: str = Field(default="https://api.deepseek.com")

    # Data retention (days, 0 = keep forever)
    data_retention_days: int = Field(default=90, ge=0)
    trace_retention_days: int = Field(default=30, ge=0)
    artifact_retention_days: int = Field(default=30, ge=0)
    model_call_retention_days: int = Field(default=60, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
