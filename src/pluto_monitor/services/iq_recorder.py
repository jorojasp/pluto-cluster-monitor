from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np


class IqRecorder:
    """Save raw captures as NPZ so measurements can be reprocessed later.

    Enabled with runtime.save_iq. Storing stops once max_captures is
    reached, because continuous captures fill the disk quickly.
    """

    def __init__(self, directory: str | Path, config: dict, max_captures: int = 500) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = Path(directory)
        self.path = base / f"iq_{stamp}"
        suffix = 1
        while self.path.exists():
            self.path = base / f"iq_{stamp}_{suffix}"
            suffix += 1
        self.path.mkdir(parents=True)
        (self.path / "config.json").write_text(
            json.dumps({key: config[key] for key in ("app", "rf")}, indent=2), encoding="utf-8"
        )
        self.max_captures = int(max_captures)
        self.count = 0

    def __call__(self, timestamp: float, group: str, radio_id: str, iq: np.ndarray) -> None:
        if self.count >= self.max_captures:
            return
        np.savez(
            self.path / f"capture_{self.count:05d}.npz",
            iq=np.asarray(iq, dtype=np.complex64),
            timestamp=timestamp,
            group=group,
            radio_id=radio_id,
        )
        self.count += 1


def recorder_from_config(config: dict) -> IqRecorder | None:
    runtime = config.get("runtime", {})
    if not runtime.get("save_iq", False):
        return None
    return IqRecorder(
        runtime.get("iq_dir", "data/raw"), config, runtime.get("iq_max_captures", 500)
    )
