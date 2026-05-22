from __future__ import annotations

import numpy as np


def compute_sinewave_detailed_metrics(
    iq: np.ndarray,
    eps: float = 1e-12,
) -> dict[str, float]:
    if iq.size == 0:
        return {
            "signal_power": float("nan"),
            "noise_power": float("nan"),
            "power_db": float("nan"),
            "noise_db": float("nan"),
            "snr_db": float("nan"),
        }

    signal_power = float(np.mean(np.abs(iq) ** 2))
    centered = iq - np.mean(iq)
    noise_power = float(np.var(centered))

    power_db = float(10.0 * np.log10(signal_power + eps))
    noise_db = float(10.0 * np.log10(noise_power + eps))

    useful_power = max(signal_power - noise_power, eps)
    snr_db = float(10.0 * np.log10(useful_power / (noise_power + eps)))

    return {
        "signal_power": signal_power,
        "noise_power": noise_power,
        "power_db": power_db,
        "noise_db": noise_db,
        "snr_db": snr_db,
    }


def compute_sinewave_metrics(
    iq: np.ndarray,
    eps: float = 1e-12,
) -> tuple[float, float]:
    metrics = compute_sinewave_detailed_metrics(iq, eps=eps)
    return metrics["power_db"], metrics["snr_db"]