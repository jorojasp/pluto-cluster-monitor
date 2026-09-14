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

    mode: Optional[str] = Field(default=None, description="SineWave | BPSK | QPSK | 16QAM")
    center_frequency_hz: Optional[int] = None
    sample_rate_hz: Optional[int] = None
    rx_gain_db: Optional[float] = None
    tx_gain_db: Optional[float] = None
    tone_frequency_hz: Optional[float] = None
    sps: Optional[int] = None
    data_bits: Optional[int] = None
    update_period_s: Optional[float] = None


class StatusResponse(BaseModel):
    state: str
    mode: Optional[str] = None
    error: Optional[str] = None
    connected_radios: list[str] = Field(default_factory=list)
    groups: dict[str, list[str]] = Field(default_factory=dict)


class RadioMetric(BaseModel):
    uri: str
    serial: Optional[str] = None
    power_db: Optional[float] = None
    snr_db: Optional[float] = None
    is_strongest: bool = False
    is_weakest: bool = False


class GroupMetrics(BaseModel):
    radios: list[RadioMetric]
    mean_power_db: Optional[float] = None
    mean_noise_db: Optional[float] = None
    strongest_label: Optional[str] = None
    strongest_db: Optional[float] = None
    weakest_label: Optional[str] = None
    weakest_db: Optional[float] = None


class MetricsSnapshot(BaseModel):
    timestamp: float
    strongest_group: str
    groups: dict[str, GroupMetrics]
