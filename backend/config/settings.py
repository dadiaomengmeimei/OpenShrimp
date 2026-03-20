"""
Global settings for the AI App Store platform.
All actual values should be configured in the .env file.
This file only defines the schema and placeholder defaults.
"""
from pydantic_settings import BaseSettings
from typing import Optional


class LLMSettings(BaseSettings):
    """LLM provider configuration (shared across all apps)."""
    provider: str = ""
    api_key: str = ""
    api_base: Optional[str] = None
    model: str = ""
    temperature: float = 0.01
    max_tokens: int = 4096

    class Config:
        env_prefix = "LLM_"


class ASRSettings(BaseSettings):
    """ASR (Automatic Speech Recognition) configuration."""
    provider: str = ""
    api_key: str = ""
    api_base: Optional[str] = None
    model: str = ""

    class Config:
        env_prefix = "ASR_"


class PlatformSettings(BaseSettings):
    """Platform-level settings."""
    app_name: str = "OpenShrimp"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = ""
    data_dir: str = "./data"
    db_url: str = "sqlite+aiosqlite:///./data/platform.db"

    class Config:
        env_prefix = "PLATFORM_"


class AuthSettings(BaseSettings):
    """Authentication configuration (JWT-based)."""
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours
    default_admin_username: str = "admin"
    default_admin_password: str = "admin123"

    class Config:
        env_prefix = "AUTH_"


# Singleton instances
llm_settings = LLMSettings()
asr_settings = ASRSettings()
platform_settings = PlatformSettings()
auth_settings = AuthSettings()
