from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["SineWave", "BPSK", "QPSK", "16QAM"] | None = None
    center_frequency_hz: int | None = Field(default=None, gt=0)
    sample_rate_hz: int | None = Field(default=None, gt=0)
    rx_gain_db: float | None = None
    tx_gain_db: float | None = Field(default=None, le=0)
    tone_frequency_hz: float | None = Field(default=None, ge=0)
    sps: int | None = Field(default=None, ge=1)
    data_bits: int | None = Field(default=None, ge=1)
    update_period_s: float | None = Field(default=None, gt=0)