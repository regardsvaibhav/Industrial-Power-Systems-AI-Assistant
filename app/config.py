"""Application settings, loaded from environment variables (and an optional .env file).

Secrets (LLM_API_KEY, ADMIN_TOKEN) are held as SecretStr so they never appear in
reprs, logs, or API responses.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Industrial Power Systems AI Assistant"
    environment: str = "development"

    # LLM (any OpenAI-compatible Chat Completions API). Empty key => offline extractive mode.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-4o-mini"
    llm_timeout_s: float = Field(30.0, gt=0, le=120)
    llm_max_tokens: int = Field(700, gt=0, le=4000)
    llm_price_input_per_mtok: float = Field(0.0, ge=0)
    llm_price_output_per_mtok: float = Field(0.0, ge=0)

    # Storage
    data_dir: Path = PROJECT_ROOT / "data"
    corpus_dir: Path = PROJECT_ROOT / "data" / "corpus"
    chroma_dir: Path = PROJECT_ROOT / "data" / "chroma"
    upload_dir: Path = PROJECT_ROOT / "data" / "uploads"
    collection_name: str = "power_docs"

    # Retrieval
    top_k: int = Field(5, ge=1, le=20)
    min_relevance: float = Field(0.35, ge=0.0, le=1.0)
    chunk_size_chars: int = Field(900, ge=200, le=4000)
    chunk_overlap_chars: int = Field(150, ge=0, le=1000)

    # Upload limits
    max_upload_mb: int = Field(15, ge=1, le=100)
    max_pdf_pages: int = Field(300, ge=1, le=2000)
    max_question_chars: int = Field(2000, ge=10, le=10000)

    # Optional bearer token protecting document write endpoints
    admin_token: SecretStr = SecretStr("")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
