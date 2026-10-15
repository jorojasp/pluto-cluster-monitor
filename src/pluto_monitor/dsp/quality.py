from __future__ import annotations

import numpy as np


def decision_directed_metrics(
    total_power: float, reference_power: float, error_power: float, eps: float = 1e-12,
) -> dict[str, float]:
    """Return EVM-based SNR and equivalent input-referred error power.

    Symbol-domain error includes noise, synchronization error and distortion.
    Its ratio is referred to total IQ power using P_noise = P_total/(1+SNR).
    This is an estimate, not a calibrated thermal-noise measurement.
    """
    values = (total_power, reference_power, error_power)
    if not all(np.isfinite(v) for v in values) or total_power < 0 or reference_power <= 0 or error_power < 0:
        raise ValueError("Invalid signal or error power")
    noise = total_power * error_power / (reference_power + error_power)
    return {
        "signal_power": total_power,
        "power_db": float(10 * np.log10(total_power + eps)),
        "noise_power": noise,
        "noise_db": float(10 * np.log10(noise + eps)),
        "snr_db": float(10 * np.log10(reference_power / max(error_power, eps))),
    }
