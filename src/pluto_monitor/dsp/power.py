from __future__ import annotations

import numpy as np


def compute_linear_power(iq: np.ndarray) -> float:
    """Mean linear power of an IQ array: mean(|iq|^2)."""
    iq = np.asarray(iq)
    if iq.size == 0:
        return float("nan")
    return float(np.mean(np.abs(iq) ** 2))


def compute_power_db(iq: np.ndarray, eps: float = 1e-12) -> float:
    """Mean power of an IQ array expressed in dB."""
    linear_power = compute_linear_power(iq)
    if linear_power != linear_power:  # NaN check
        return float("nan")
    return float(10.0 * np.log10(linear_power + eps))
