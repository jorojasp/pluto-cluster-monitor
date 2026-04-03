import numpy as np


def compute_linear_power(iq: np.ndarray) -> float:
    if iq.size == 0:
        return float("nan")
    return float(np.mean(np.abs(iq) ** 2))


def compute_power_db(iq: np.ndarray, eps: float = 1e-12) -> float:
    power = compute_linear_power(iq)
    if np.isnan(power):
        return float("nan")
    return float(10.0 * np.log10(power + eps))