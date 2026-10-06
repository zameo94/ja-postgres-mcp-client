from types import SimpleNamespace

import pytest
import uvicorn

from app.main import create_app, lifespan, run


async def test_lifespan_loads_settings_onto_app_state(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr("app.main.get_settings", lambda: sentinel)

    app = create_app()
    async with lifespan(app):
        assert app.state.settings is sentinel


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
    settings = SimpleNamespace(host="0.0.0.0", port=9999, log_level="DEBUG", is_development=False)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))

    run()

    assert captured == {
        "host": "0.0.0.0",
        "port": 9999,
        "log_level": "debug",
        "reload": False,
    }
