from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StartRequest(BaseModel):
    """Optional overrides applied on top of the base YAML config.

    Any field left as null keeps whatever value is already in the config
    file (e.g. `configs/default.yaml`). Radio wiring (serials per group,
    transmitter serial) is not overridable from here yet -- edit the YAML
    for that.
    """

    transmit_enabled: Optional[bool] = None
    mode: Optional[str] = Field(default=None, description="One of the names in /api/config modes")
    center_frequency_hz: Optional[int] = None
    sample_rate_hz: Optional[int] = None
    rx_gain_db: Optional[float] = None
    tx_gain_db: Optional[float] = None
    tone_frequency_hz: Optional[float] = None
    sps: Optional[int] = None
    data_bits: Optional[int] = None
    update_period_s: Optional[float] = None
