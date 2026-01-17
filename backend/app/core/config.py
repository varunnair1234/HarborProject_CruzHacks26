from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Database
    database_url: str = "sqlite:///./harbor.db"

    # API Keys
    openrouter_api_key: Optional[str] = None
    google_api_key: Optional[str] = None

    # If you set DEEPSEEK_API_KEY in Render, this prevents the crash
    deepseek_api_key: Optional[str] = Field(default=None, alias="DEEPSEEK_API_KEY")

    openrouter_api_key: Optional[str] = Field(default=None, alias="OPENROUTER_API_KEY")
    google_api_key: Optional[str] = Field(default=None, alias="GOOGLE_API_KEY")

    # LLM Models
    deepseek_r1_model: str = "deepseek/deepseek-r1"
    deepseek_v3_model: str = "deepseek/deepseek-chat"
    gemini_model: str = "gemini-2.0-flash-exp"

    # Cache Configuration
    llm_cache_ttl_hours: int = 24
    external_cache_ttl_hours: int = 6

    # App Configuration
    app_version: str = "1.0.0"
    environment: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )


# Global settings instance
settings = Settings()
