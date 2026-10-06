from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import (
    DEFAULT_OLLAMA_BASE_URL,
    ENV_FILE,
    PROJECT_ROOT,
    Settings,
)

MCP_URL = "http://localhost:8000/mcp"


def test_requires_mcp_server_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JA_CLIENT_MCP_SERVER_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_applies_development_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_CLIENT_MCP_SERVER_URL", MCP_URL)
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.is_development is True
    assert settings.log_level == "INFO"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8100
    assert settings.mcp_server_url == MCP_URL
    assert settings.mcp_connect_timeout == 10.0
    assert settings.mcp_tool_timeout == 30.0
    assert settings.ollama_base_url == DEFAULT_OLLAMA_BASE_URL


def test_reads_and_overrides_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_CLIENT_MCP_SERVER_URL", "https://mcp.example.com/mcp/")
    monkeypatch.setenv("JA_CLIENT_ENVIRONMENT", "production")
    monkeypatch.setenv("JA_CLIENT_HOST", "0.0.0.0")
    monkeypatch.setenv("JA_CLIENT_PORT", "9000")
    monkeypatch.setenv("JA_CLIENT_MCP_TOOL_TIMEOUT", "45")
    settings = Settings(_env_file=None)

    assert settings.mcp_server_url == "https://mcp.example.com/mcp/"
    assert settings.is_development is False
    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.mcp_tool_timeout == 45.0


@pytest.mark.parametrize("url", ["not-a-url", "ftp://example.com/mcp", "http:///mcp"])
def test_rejects_invalid_mcp_url(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("JA_CLIENT_MCP_SERVER_URL", url)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("port", ["0", "70000", "-1"])
def test_rejects_out_of_range_port(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("JA_CLIENT_MCP_SERVER_URL", MCP_URL)
    monkeypatch.setenv("JA_CLIENT_PORT", port)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_env_file_is_anchored_to_project_root() -> None:
    assert ENV_FILE == PROJECT_ROOT / ".env"
    assert ENV_FILE.is_absolute()


def test_real_environment_wins_over_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("JA_CLIENT_MCP_SERVER_URL=http://from-file.invalid/mcp\n")
    monkeypatch.setenv("JA_CLIENT_MCP_SERVER_URL", "http://from-env.invalid/mcp")

    settings = Settings(_env_file=env_file)

    assert settings.mcp_server_url == "http://from-env.invalid/mcp"


def test_system_prompt_has_default_and_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_CLIENT_MCP_SERVER_URL", MCP_URL)
    monkeypatch.delenv("JA_CLIENT_SYSTEM_PROMPT", raising=False)

    assert Settings(_env_file=None).system_prompt

    monkeypatch.setenv("JA_CLIENT_SYSTEM_PROMPT", "custom instructions")

    assert Settings(_env_file=None).system_prompt == "custom instructions"
