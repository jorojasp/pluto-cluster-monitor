from __future__ import annotations

import numpy as np
from scipy.optimize import minimize_scalar


def build_tone(tone_frequency_hz: float, sample_rate_hz: float, num_samples: int) -> np.ndarray:
    """Complex tone with a whole number of cycles in the repeated TX buffer.

    The frequency is rounded to the nearest buffer bin; otherwise every
    repetition would start with a phase jump and radiate spurs.
    """
    cycles = round(tone_frequency_hz * num_samples / sample_rate_hz)
    if cycles == 0:
        cycles = 1 if tone_frequency_hz >= 0 else -1
    n = np.arange(num_samples)
    return np.exp(2j * np.pi * cycles * n / num_samples).astype(np.complex64)


def compute_sinewave_detailed_metrics(
    iq: np.ndarray,
    eps: float = 1e-12,
    *,
    sample_rate_hz: float = 1.0,
    tone_frequency_hz: float | None = None,
) -> dict[str, float]:
    """Fit a complex tone plus DC; measure residual power in input IQ units.

    Search near the requested tone to allow oscillator offset. A spectral
    detection gate avoids reporting a fitted noise peak as a valid tone SNR.
    Power is uncalibrated dB relative to the input sample units, not dBm.
    """
    iq = np.asarray(iq, dtype=np.complex128).ravel()
    invalid = {key: float("nan") for key in
               ("signal_power", "noise_power", "power_db", "noise_db", "snr_db", "tone_frequency_hz")}
    if iq.size < 8 or not np.all(np.isfinite(iq)) or sample_rate_hz <= 0:
        return invalid
    total = float(np.mean(np.abs(iq) ** 2))
    centered = iq - np.mean(iq)
    centered_power = float(np.mean(np.abs(centered) ** 2))
    result = dict(invalid, signal_power=total,
                  power_db=float(10 * np.log10(total + eps)),
                  noise_power=centered_power,
                  noise_db=float(10 * np.log10(centered_power + eps)))
    if centered_power <= eps:
        return result
    n = np.arange(iq.size)
    frequencies = np.fft.fftfreq(iq.size)
    spectrum = np.abs(np.fft.fft(centered * np.hanning(iq.size))) ** 2
    mask = np.abs(frequencies) > 1.5 / iq.size
    if tone_frequency_hz is not None:
        expected = tone_frequency_hz / sample_rate_hz
        tolerance = max(0.02, 4 / iq.size)
        distance = np.abs((frequencies - expected + 0.5) % 1.0 - 0.5)
        mask &= distance <= tolerance
    candidates = np.flatnonzero(mask)
    if not candidates.size:
        return result
    peak = int(candidates[np.argmax(spectrum[candidates])])
    floor = float(np.median(spectrum[np.abs(frequencies) > 1.5 / iq.size]))
    if spectrum[peak] < 20 * max(floor, eps):
        return result

    def fit(frequency):
        carrier = np.exp(2j * np.pi * frequency * n)
        carrier -= np.mean(carrier)
        energy = float(np.vdot(carrier, carrier).real)
        coefficient = np.vdot(carrier, centered) / max(energy, eps)
        return coefficient * carrier

    def objective(frequency):
        return float(np.mean(np.abs(centered - fit(frequency)) ** 2))

    estimate = minimize_scalar(
        objective,
        bounds=(frequencies[peak] - 1 / iq.size, frequencies[peak] + 1 / iq.size),
        method="bounded", options={"xatol": 1e-12, "maxiter": 32},
    )
    fitted = fit(estimate.x)
    tone_power = float(np.mean(np.abs(fitted) ** 2))
    noise = objective(estimate.x)
    result.update(
        noise_power=noise,
        noise_db=float(10 * np.log10(noise + eps)),
        snr_db=float(10 * np.log10((tone_power + eps) / (noise + eps))),
        tone_frequency_hz=float(estimate.x * sample_rate_hz),
    )
    return result
