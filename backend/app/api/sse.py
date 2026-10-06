"""Server-Sent Events encoder for our own chat event contract.

``json.dumps`` produces a single line, so each event uses exactly one ``data:``
field. The frontend consumes this with ``fetch`` + ``ReadableStream``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def format_sse(event: str, data: Mapping[str, Any]) -> str:
    """Encode one SSE event with a JSON payload."""
    payload = json.dumps(dict(data), ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"
