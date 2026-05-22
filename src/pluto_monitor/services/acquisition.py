from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from pluto_monitor.dsp.bpsk import compute_bpsk_detailed_metrics, compute_bpsk_metrics
from pluto_monitor.dsp.qam16 import compute_qam16_detailed_metrics, compute_qam16_metrics
from pluto_monitor.dsp.qpsk import compute_qpsk_detailed_metrics, compute_qpsk_metrics
from pluto_monitor.dsp.sinewave import compute_sinewave_detailed_metrics
from pluto_monitor.hardware.receiver import PlutoReceiver
from pluto_monitor.services.clustering import GroupSummary, summarize_group


@dataclass
class AcquisitionResult:
    timestamp: float
    group_powers: dict[str, dict[str, float]]
    group_snrs: dict[str, dict[str, float]]
    group_summaries: dict[str, GroupSummary]
    strongest_group: str
    group_mean_power_db: dict[str, float]
    group_mean_noise_db: dict[str, float]


def _compute_metrics_for_mode(
    iq,
    mode: str,
    rf_config: dict,
) -> tuple[float, float]:
    if mode == "BPSK":
        return compute_bpsk_metrics(
            iq=iq,
            sample_rate_hz=rf_config["sample_rate_hz"],
            data_bits=rf_config["data_bits"],
            sps=rf_config["sps"],
        )

    if mode == "QPSK":
        return compute_qpsk_metrics(
            iq=iq,
            sample_rate_hz=rf_config["sample_rate_hz"],
            data_bits=rf_config["data_bits"],
            sps=rf_config["sps"],
        )

    if mode == "16QAM":
        return compute_qam16_metrics(
            iq=iq,
            sample_rate_hz=rf_config["sample_rate_hz"],
            data_bits=rf_config["data_bits"],
            sps=rf_config["sps"],
        )

    raise NotImplementedError(f"Mode {mode} is not implemented in acquisition")


def acquire_once(
    groups: dict[str, dict],
    receivers: dict[str, PlutoReceiver],
    mode: str,
    rf_config: dict,
) -> AcquisitionResult:
    timestamp = time.time()
    group_powers: dict[str, dict[str, float]] = {}
    group_snrs: dict[str, dict[str, float]] = {}
    group_summaries: dict[str, GroupSummary] = {}
    group_mean_power_db: dict[str, float] = {}
    group_mean_noise_db: dict[str, float] = {}

    strongest_group = "---"
    strongest_group_peak = float("-inf")

    for group_name, group_data in groups.items():
        power_map: dict[str, float] = {}
        snr_map: dict[str, float] = {}

        group_signal_linear: list[float] = []
        group_noise_linear: list[float] = []

        for radio_id in group_data["radio_ids"]:
            receiver = receivers[radio_id]
            iq = receiver.read_samples()

            if mode == "SineWave":
                metrics = compute_sinewave_detailed_metrics(iq)
                power_db = metrics["power_db"]
                snr_db = metrics["snr_db"]

                if not np.isnan(metrics["signal_power"]):
                    group_signal_linear.append(metrics["signal_power"])
                if not np.isnan(metrics["noise_power"]):
                    group_noise_linear.append(metrics["noise_power"])

            elif mode == "BPSK":
                metrics = compute_bpsk_detailed_metrics(
                    iq=iq,
                    sample_rate_hz=rf_config["sample_rate_hz"],
                    data_bits=rf_config["data_bits"],
                    sps=rf_config["sps"],
                )
                power_db = metrics["power_db"]
                snr_db = metrics["snr_db"]

                if not np.isnan(metrics["signal_power"]):
                    group_signal_linear.append(metrics["signal_power"])
                if not np.isnan(metrics["noise_power"]):
                    group_noise_linear.append(metrics["noise_power"])

            elif mode == "QPSK":
                metrics = compute_qpsk_detailed_metrics(
                    iq=iq,
                    sample_rate_hz=rf_config["sample_rate_hz"],
                    data_bits=rf_config["data_bits"],
                    sps=rf_config["sps"],
                )
                power_db = metrics["power_db"]
                snr_db = metrics["snr_db"]

                if not np.isnan(metrics["signal_power"]):
                    group_signal_linear.append(metrics["signal_power"])
                if not np.isnan(metrics["noise_power"]):
                    group_noise_linear.append(metrics["noise_power"])

            elif mode == "16QAM":
                metrics = compute_qam16_detailed_metrics(
                    iq=iq,
                    sample_rate_hz=rf_config["sample_rate_hz"],
                    data_bits=rf_config["data_bits"],
                    sps=rf_config["sps"],
                )
                power_db = metrics["power_db"]
                snr_db = metrics["snr_db"]

                if not np.isnan(metrics["signal_power"]):
                    group_signal_linear.append(metrics["signal_power"])
                if not np.isnan(metrics["noise_power"]):
                    group_noise_linear.append(metrics["noise_power"])

            else:
                power_db, snr_db = _compute_metrics_for_mode(
                    iq=iq,
                    mode=mode,
                    rf_config=rf_config,
                )

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

        if group_signal_linear:
            mean_signal_linear = float(np.mean(group_signal_linear))
            group_mean_power_db[group_name] = float(
                10.0 * np.log10(mean_signal_linear + 1e-12)
            )
        else:
            group_mean_power_db[group_name] = float("nan")

        if group_noise_linear:
            mean_noise_linear = float(np.mean(group_noise_linear))
            group_mean_noise_db[group_name] = float(
                10.0 * np.log10(mean_noise_linear + 1e-12)
            )
        else:
            group_mean_noise_db[group_name] = float("nan")

    return AcquisitionResult(
        timestamp=timestamp,
        group_powers=group_powers,
        group_snrs=group_snrs,
        group_summaries=group_summaries,
        strongest_group=strongest_group,
        group_mean_power_db=group_mean_power_db,
        group_mean_noise_db=group_mean_noise_db,
    )