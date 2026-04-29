from __future__ import annotations

import numpy as np


def compute_sinewave_metrics(
    iq: np.ndarray,
    eps: float = 1e-12,
) -> tuple[float, float]:

    if iq.size == 0:
        return float("nan"), float("nan")

    signal_power = float(np.mean(np.abs(iq) ** 2))

    centered = iq - np.mean(iq)
    noise_power = float(np.var(centered))

    power_db = float(10.0 * np.log10(signal_power + eps))

    useful_power = max(signal_power - noise_power, eps)
    snr_db = float(10.0 * np.log10(useful_power / (noise_power + eps)))

    return power_db, snr_db