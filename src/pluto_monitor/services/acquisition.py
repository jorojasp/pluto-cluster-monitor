from __future__ import annotations

import time
from dataclasses import dataclass

from pluto_monitor.dsp.sinewave import compute_sinewave_metrics
from pluto_monitor.hardware.receiver import PlutoReceiver
from pluto_monitor.services.clustering import GroupSummary, summarize_group


@dataclass
class AcquisitionResult:
    timestamp: float
    group_powers: dict[str, dict[str, float]]
    group_snrs: dict[str, dict[str, float]]
    group_summaries: dict[str, GroupSummary]
    strongest_group: str


def acquire_once(
    groups: dict[str, dict],
    receivers: dict[str, PlutoReceiver],
) -> AcquisitionResult:
    timestamp = time.time()
    group_powers: dict[str, dict[str, float]] = {}
    group_snrs: dict[str, dict[str, float]] = {}
    group_summaries: dict[str, GroupSummary] = {}

    strongest_group = "---"
    strongest_group_peak = float("-inf")

    for group_name, group_data in groups.items():
        power_map: dict[str, float] = {}
        snr_map: dict[str, float] = {}

        for radio_id in group_data["radio_ids"]:
            receiver = receivers[radio_id]
            iq = receiver.read_samples()
            power_db, snr_db = compute_sinewave_metrics(iq)

            power_map[radio_id] = power_db
            snr_map[radio_id] = snr_db

        group_powers[group_name] = power_map
        group_snrs[group_name] = snr_map

        summary = summarize_group(power_map)
        group_summaries[group_name] = summary

        if summary.strongest_db == summary.strongest_db:
            if summary.strongest_db > strongest_group_peak:
                strongest_group_peak = summary.strongest_db
                strongest_group = group_name

    return AcquisitionResult(
        timestamp=timestamp,
        group_powers=group_powers,
        group_snrs=group_snrs,
        group_summaries=group_summaries,
        strongest_group=strongest_group,
    )