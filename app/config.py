from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AppSettings(BaseSettings):
    newsapi_key: str = ""
    llm_provider: str = "ollama"
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3:8b"
    llm_api_key: str = ""

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def is_configured(self) -> bool:
        has_llm = bool(self.llm_base_url and self.llm_model)
        has_cloud_key = self.llm_provider == "ollama" or bool(self.llm_api_key)
        return has_llm and has_cloud_key


class SetupInput(BaseModel):
    newsapi_key: str = ""
    llm_provider: str = Field(pattern="^(ollama|cloud)$")
    llm_base_url: str
    llm_model: str
    llm_api_key: str = ""

    @field_validator("newsapi_key", "llm_base_url", "llm_model", "llm_api_key")
    @classmethod
    def clean_value(cls, value: str) -> str:
        value = value.strip()
        if "\n" in value or "\r" in value:
            raise ValueError("Values cannot contain line breaks")
        return value

    def validate_complete(self) -> None:
        if not self.llm_base_url:
            raise ValueError("The LLM base URL is required")
        if not self.llm_model:
            raise ValueError("The model name is required")
        if self.llm_provider == "cloud" and not self.llm_api_key:
            raise ValueError("An API key is required for a cloud model")


class SettingsManager:
    def __init__(self, env_path: Path | None = None):
        override = os.getenv("NEWSBOT_ENV_FILE")
        self.env_path = Path(override) if override else (env_path or PROJECT_ROOT / ".env")

    def load(self) -> AppSettings:
        return AppSettings(_env_file=self.env_path, _env_file_encoding="utf-8")

    def is_configured(self) -> bool:
        return self.env_path.is_file() and self.load().is_configured

    def save(self, data: SetupInput) -> AppSettings:
        data.validate_complete()
        current = self.load() if self.env_path.is_file() else AppSettings()
        values = {
            "NEWSAPI_KEY": data.newsapi_key or current.newsapi_key,
            "LLM_PROVIDER": data.llm_provider,
            "LLM_BASE_URL": data.llm_base_url,
            "LLM_MODEL": data.llm_model,
            "LLM_API_KEY": data.llm_api_key or current.llm_api_key,
        }
        content = "".join(f'{key}="{_escape(value)}"\n' for key, value in values.items())
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.env_path.with_suffix(".tmp")
        temporary_path.write_text(content, encoding="utf-8")
        temporary_path.replace(self.env_path)
        return self.load()


def masked_settings(settings: AppSettings, configured: bool | None = None) -> dict[str, str | bool]:
    return {
        "configured": settings.is_configured if configured is None else configured,
        "has_newsapi_key": bool(settings.newsapi_key),
        "llm_provider": settings.llm_provider,
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "has_llm_api_key": bool(settings.llm_api_key),
    }


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
