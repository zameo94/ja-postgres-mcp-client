import logging

from app.core.logging import configure_logging


def test_configure_logging_sets_level_and_is_idempotent() -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        root.handlers.clear()

        configure_logging("warning")
        assert root.level == logging.WARNING
        handler_count = len(root.handlers)

        configure_logging("debug")
        assert root.level == logging.DEBUG
        assert len(root.handlers) == handler_count
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)


def test_configure_logging_falls_back_to_info_for_unknown_level() -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        root.handlers.clear()

        configure_logging("not-a-level")

        assert root.level == logging.INFO
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)
