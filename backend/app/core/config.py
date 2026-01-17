from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Database
    database_url: str = Field(default="sqlite:///./harbor.db", alias="DATABASE_URL")

    # API Keys
    openrouter_api_key: Optional[str] = Field(default=None, alias="OPENROUTER_API_KEY")
    google_api_key: Optional[str] = Field(default=None, alias="GOOGLE_API_KEY")
    deepseek_api_key: Optional[str] = Field(default=None, alias="DEEPSEEK_API_KEY")

    # LLM Models
    deepseek_r1_model: str = "deepseek/deepseek-r1"
    deepseek_v3_model: str = "deepseek/deepseek-chat"
    gemini_model: str = "gemini-2.0-flash-exp"

    # Cache Configuration
    llm_cache_ttl_hours: int = 24
    external_cache_ttl_hours: int = 6

    # App Configuration
    app_version: str = "1.0.0"
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # NWS Weather API
    nws_user_agent: str = Field(default="harborproject.app, your_email@domain.com", alias="NWS_USER_AGENT")

    # JWT Authentication
    secret_key: str = Field(default="your-secret-key-change-in-production", alias="SECRET_KEY")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )


settings = Settings()
