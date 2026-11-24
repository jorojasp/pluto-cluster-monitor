from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from pluto_monitor.dsp.modes import get_mode
from pluto_monitor.hardware.receiver import PlutoReceiver
from pluto_monitor.services.clustering import GroupSummary, summarize_group

# Called with (timestamp, group, radio_id, iq) for every capture.
IqSink = Callable[[float, str, str, np.ndarray], None]


@dataclass
class AcquisitionResult:
    timestamp: float
    group_powers: dict[str, dict[str, float]]
    group_snrs: dict[str, dict[str, float]]
    group_summaries: dict[str, GroupSummary]
    strongest_group: str
    group_mean_power_db: dict[str, float]
    group_mean_noise_db: dict[str, float]
    # Full metrics of each radio: group -> radio_id -> metric name -> value.
    group_metrics: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)


def _mean_db(values: list[float]) -> float:
    """Average linear powers, ignoring NaN, and convert to dB."""
    valid = [value for value in values if not np.isnan(value)]
    if not valid:
        return float("nan")
    return float(10.0 * np.log10(np.mean(valid) + 1e-12))


def acquire_once(
    groups: dict[str, dict],
    receivers: dict[str, PlutoReceiver],
    mode: str,
    rf_config: dict,
    iq_sink: IqSink | None = None,
) -> AcquisitionResult:
    """Capture and measure every radio once. Radios are read one after another."""
    selected = get_mode(mode)
    timestamp = time.time()
    metrics: dict[str, dict[str, dict[str, float]]] = {}

    for group_name, group_data in groups.items():
        metrics[group_name] = {}
        for radio_id in group_data["radio_ids"]:
            iq = receivers[radio_id].read_samples()
            if iq_sink is not None:
                iq_sink(timestamp, group_name, radio_id, iq)
            measured = selected.measure(iq, rf_config)
            # Largest I or Q code (full scale 2048): a few codes means the RX
            # gain is too low, values near full scale mean saturation.
            measured["adc_peak"] = float(max(np.abs(iq.real).max(), np.abs(iq.imag).max()))
            metrics[group_name][radio_id] = measured

    powers = {
        group: {radio: m["power_db"] for radio, m in radios.items()}
        for group, radios in metrics.items()
    }
    summaries = {group: summarize_group(power_map) for group, power_map in powers.items()}
    valid_groups = [g for g, s in summaries.items() if not np.isnan(s.strongest_db)]
    strongest_group = (
        max(valid_groups, key=lambda g: summaries[g].strongest_db) if valid_groups else "---"
    )

    return AcquisitionResult(
        timestamp=timestamp,
        group_powers=powers,
        group_snrs={
            group: {radio: m["snr_db"] for radio, m in radios.items()}
            for group, radios in metrics.items()
        },
        group_summaries=summaries,
        strongest_group=strongest_group,
        group_mean_power_db={
            group: _mean_db([m["signal_power"] for m in radios.values()])
            for group, radios in metrics.items()
        },
        group_mean_noise_db={
            group: _mean_db([m["noise_power"] for m in radios.values()])
            for group, radios in metrics.items()
        },
        group_metrics=metrics,
    )
