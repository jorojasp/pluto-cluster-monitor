"""Runtime overrides and validation shared by the local and distributed paths."""
from __future__ import annotations

import copy
import math
from typing import Any

from pluto_monitor.dsp.modes import get_mode

APP_FIELDS = {"mode", "update_period_s", "transmit_enabled"}
RF_INT_FIELDS = {"center_frequency_hz", "sample_rate_hz", "samples_per_frame", "sps", "data_bits"}
RF_FLOAT_FIELDS = {"rx_gain_db", "tx_gain_db", "tone_frequency_hz"}

# ADALM-Pluto limits (AD9363 tuning range, libiio sample rates and gains).
_LIMITS = {
    "center_frequency_hz": (325e6, 3.8e9),
    "sample_rate_hz": (521e3, 61.44e6),
    "samples_per_frame": (64, 2**20),
    "sps": (1, 64),
    "data_bits": (1, 2**16),
    "rx_gain_db": (-3, 71),
    "tx_gain_db": (-89.75, 0),
}


def validate(config: dict[str, Any]) -> None:
    """Raise ValueError for settings the radios or the selected mode cannot use."""
    app, rf = config["app"], config["rf"]
    period = float(app["update_period_s"])
    if not math.isfinite(period) or period <= 0:
        raise ValueError("update_period_s must be > 0")
    for name, (low, high) in _LIMITS.items():
        if name in rf and not low <= float(rf[name]) <= high:
            raise ValueError(f"{name} must be between {low:g} and {high:g}")
    get_mode(app["mode"]).validate(rf)


def apply_overrides(
    config: dict[str, Any],
    app: dict[str, Any] | None = None,
    rf: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a validated copy of config with the allowed overrides applied.

    Radio wiring (serials and groups) always stays in the YAML file.
    """
    result = copy.deepcopy(config)
    for key, value in (app or {}).items():
        if key in APP_FIELDS and value is not None:
            result["app"][key] = value
    for key, value in (rf or {}).items():
        if value is None:
            continue
        if key in RF_INT_FIELDS:
            result["rf"][key] = int(value)
        elif key in RF_FLOAT_FIELDS:
            result["rf"][key] = float(value)
    validate(result)
    return result


def split_overrides(overrides: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a flat request into (app, rf) overrides."""
    app = {k: v for k, v in overrides.items() if k in APP_FIELDS}
    rf = {k: v for k, v in overrides.items() if k in RF_INT_FIELDS | RF_FLOAT_FIELDS}
    return app, rf
