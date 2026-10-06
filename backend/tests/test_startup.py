from types import SimpleNamespace

import pytest
import uvicorn

from app.main import create_app, lifespan, run


async def test_lifespan_loads_settings_onto_app_state(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(mcp_server_url="http://mcp.local/mcp")
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    app = create_app()
    async with lifespan(app):
        assert app.state.settings is settings
        assert app.state.mcp is not None


async def test_lifespan_propagates_settings_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise RuntimeError("invalid configuration")

    monkeypatch.setattr("app.main.get_settings", boom)

    app = create_app()
    with pytest.raises(RuntimeError):
        async with lifespan(app):
            pass


def test_run_uses_settings_for_server_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    settings = SimpleNamespace(
        host="0.0.0.0", port=9999, log_level="DEBUG", is_development=False, reload=None
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))

    run()

    assert captured == {
        "host": "0.0.0.0",
        "port": 9999,
        "log_level": "debug",
        "reload": False,
    }


@pytest.mark.parametrize(
    ("is_development", "reload", "expected"),
    [
        (False, None, False),
        (True, None, True),
        (True, False, False),
        (False, True, True),
    ],
)
def test_run_derives_reload(
    monkeypatch: pytest.MonkeyPatch, is_development: bool, reload: bool | None, expected: bool
) -> None:
    captured: dict[str, object] = {}
    settings = SimpleNamespace(
        host="0.0.0.0",
        port=8100,
        log_level="INFO",
        is_development=is_development,
        reload=reload,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))

    run()

    assert captured["reload"] is expected
