from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Database
    database_url: str = "sqlite:///./harbor.db"
    
    # API Keys
    openrouter_api_key: str
    
    # LLM Models
    deepseek_r1_model: str = "deepseek/deepseek-r1"
    deepseek_v3_model: str = "deepseek/deepseek-chat"
    gemini_model: str = "google/gemini-1.5-flash"
    
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
        extra="ignore",  # Changed from "forbid" to "ignore" for deployment stability
    )


# Global settings instance
settings = Settings()