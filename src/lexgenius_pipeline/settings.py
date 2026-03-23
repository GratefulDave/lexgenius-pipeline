from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables with LGP_ prefix."""

    model_config = SettingsConfigDict(
        env_prefix="LGP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    db_backend: Literal["sqlite", "postgresql"] = "sqlite"
    db_path: str = "lexgenius_pipeline.db"
    db_url: str = ""

    # Compute
    compute_backend: Literal["local", "lambda"] = "local"
    max_concurrent_connectors: int = 5

    # LLM
    llm_provider: Literal["openai", "anthropic", "fixture"] = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""

    # API Keys - support both LGP_ prefixed and direct env var names
    fda_api_key: str = ""
    exa_api_key: str = ""
    comptox_api_key: str = ""
    congress_api_key: str = ""
    pubmed_api_key: str = ""
    regulations_gov_api_key: str = ""
    courtlistener_api_key: str = ""
    epa_api_key: str = ""
    pacer_username: str = ""
    pacer_password: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"

    @model_validator(mode="before")
    @classmethod
    def _read_fallback_env_vars(cls, values: Any) -> Any:
        """Read env vars without LGP_ prefix as fallback for tortintel .env compatibility."""
        mapping = {
            "fda_api_key": "FDA_API_KEY",
            "exa_api_key": "EXA_API_KEY",
            "congress_api_key": "DATA_GOV_API_KEY",
            "pubmed_api_key": "PUBMED_API_KEY",
            "regulations_gov_api_key": "REGULATIONS_GOV_API_KEY",
            "courtlistener_api_key": "COURTLISTENER_API_TOKEN",
            "epa_api_key": "EPA_API_KEY",
            "comptox_api_key": "CTX_API_KEY",
            "llm_api_key": "ANTHROPIC_API_KEY",
            "db_url": "RDS_DATABASE_URL",
        }
        for field_name, env_var in mapping.items():
            if not values.get(field_name) and not values.get(f"LGP_{field_name.upper()}"):
                env_val = os.environ.get(env_var, "")
                if env_val:
                    values[field_name] = env_val
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()
