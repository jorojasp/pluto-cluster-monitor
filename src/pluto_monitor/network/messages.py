from __future__ import annotations

import json
import time
from typing import Any


def now_ts() -> float:
    return time.time()


def dumps_message(message: dict[str, Any]) -> bytes:
    """Serialize one network message as compact UTF-8 JSON."""
    return json.dumps(message, separators=(",", ":"), allow_nan=True).encode("utf-8")


def loads_message(data: bytes) -> dict[str, Any]:
    """Parse one UTF-8 JSON message received from the network."""
    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Network message must be a JSON object")
    return obj
