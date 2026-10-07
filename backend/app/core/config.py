"""Centralized application configuration.

Every environment-specific value is read from the process environment (with an
optional ``.env`` file) exactly here, and validated once. The rest of the
application depends on the typed :class:`Settings` object, never on
``os.environ`` directly.

Configuration is split by concern:

* application -- how the HTTP server runs;
* MCP -- how to reach the separate ``ja-postgres-mcp`` server;
* provider defaults -- development fallbacks for the LLM provider, whose real
  settings are chosen by the user in the browser and sent per request.

The MVP has no server-side secrets: the external provider API key is supplied
by the client per request and is never persisted on the backend.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions about a PostgreSQL database. "
    "Answer the user's question directly and concisely, in the user's language. "
    "Never reveal your reasoning, plans or internal steps, and never show tool calls, "
    "tool or function names, or JSON: use the tools silently and reply with the final "
    "result only. If you cannot retrieve the data, say so briefly, without naming any "
    "tool or explaining the failure. "
    "Always use schema-qualified names (e.g. schema.table) and only the columns listed "
    "for each relation; if the data you need is in another relation, join it. "
    "If a query fails, read the error message, correct the query and try again before "
    "answering. "
    "Base every answer on the tool results and never invent data. "
    "If a query returns no rows, say so."
)


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Validated, environment-driven application settings.

    ``JA_CLIENT_`` is the environment variable prefix. Values are read from real
    environment variables first, then from a single canonical ``.env`` at the
    repository root (anchored to the project, independent of the working
    directory), then from field defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="JA_CLIENT_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "production"] = "development"
    log_level: LogLevel = "INFO"
    host: str = "127.0.0.1"
    port: int = Field(default=8100, ge=1, le=65535)
    reload: bool | None = None

    mcp_server_url: str
    mcp_connect_timeout: float = Field(default=10.0, gt=0)
    mcp_tool_timeout: float = Field(default=30.0, gt=0)

    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    database_schema: str | None = Field(default=None, validation_alias="JA_CLIENT_SCHEMA")

    @property
    def is_development(self) -> bool:
        """Whether the app runs in a development environment."""
        return self.environment == "development"

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value

    @field_validator("mcp_server_url", "ollama_base_url")
    @classmethod
    def _validate_http_url(cls, value: str, info: ValidationInfo) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError(f"{info.field_name} must be an absolute http(s) URL")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return process-wide settings, read from the environment once.

    Raises ``pydantic.ValidationError`` early if required values are missing or
    invalid, so misconfiguration surfaces at startup rather than on first use.
    """
    return Settings()
