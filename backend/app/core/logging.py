"""Application logging setup.

Configures the root logger once at startup from ``JA_CLIENT_LOG_LEVEL``. Log
messages must never contain secrets (API keys, authorization headers, request
bodies); expected failures are logged with their stable code and internal
``detail`` only.
"""

from __future__ import annotations

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str) -> None:
    """Set the root log level and install a formatter handler if none exists.

    Idempotent: it does not add a second handler when one is already present
    (e.g. configured by uvicorn or a test runner).
    """
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
