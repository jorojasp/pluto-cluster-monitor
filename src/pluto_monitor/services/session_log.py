from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


class SessionLog:
    """One JSONL file per measurement session. Not thread safe by itself."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.session_id: str | None = None
        self.path: str | None = None
        self._stream = None

    @property
    def active(self) -> bool:
        return self._stream is not None

    def start(self, app: dict[str, Any], rf: dict[str, Any], **fields: Any) -> None:
        self.end("replaced")
        self.directory.mkdir(parents=True, exist_ok=True)
        session_id = uuid.uuid4().hex
        path = self.directory / f"session_{session_id}.jsonl"
        self._stream = path.open("x", encoding="utf-8")
        self.session_id = session_id
        self.path = str(path.resolve())
        self.record({"type": "session_start", "session_id": session_id,
                     "timestamp": time.time(), "app": app, "rf": rf, **fields})

    def record(self, record: dict[str, Any]) -> None:
        if self._stream is None:
            return
        try:
            self._stream.write(json.dumps(record, allow_nan=False) + "\n")
            self._stream.flush()
        except (OSError, ValueError) as exc:
            print(f"Session logging failed: {exc}")

    def end(self, reason: str = "stopped") -> None:
        if self._stream is None:
            return
        self.record({"type": "session_end", "session_id": self.session_id,
                     "timestamp": time.time(), "reason": reason})
        self._stream.close()
        self._stream = None
