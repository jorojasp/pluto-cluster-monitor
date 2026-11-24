"""Simulated radio channel for tests and offline experiments."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Channel:
    """Impairments applied to a cyclic transmit waveform."""

    snr_db: float = 20.0  # per sample, over the whole sampled bandwidth
    cfo_hz: float = 0.0
    clock_ppm: float = 0.0  # sampling clock difference
    dc: complex = 0.0
    level: float = 100.0  # RMS received amplitude
    paths: tuple[tuple[float, complex], ...] = ((0.0, 1.0),)  # (delay in samples, gain)
    quantize: bool = False  # round to integer ADC codes

    def receive(
        self, waveform: np.ndarray, samples: int, sample_rate_hz: float, rng: np.random.Generator
    ) -> np.ndarray:
        """Capture from a random fractional position of the repeated waveform."""
        wave = np.asarray(waveform, dtype=np.complex128)
        size = wave.size
        freq = np.fft.fftfreq(size)
        response = sum(g * np.exp(-2j * np.pi * freq * d) for d, g in self.paths)
        shift = rng.integers(size) + rng.random()
        spectrum = np.fft.fft(wave) * response * np.exp(2j * np.pi * freq * shift)
        n = np.arange(samples)
        if self.clock_ppm:
            over = 16
            padded = np.zeros(size * over, dtype=np.complex128)
            half = size // 2
            padded[:half] = spectrum[:half]
            padded[-(size - half):] = spectrum[half:]
            fine = np.fft.ifft(padded) * over
            position = (n * (1 + self.clock_ppm * 1e-6) * over) % (size * over)
            low = position.astype(int)
            part = position - low
            iq = fine[low] * (1 - part) + fine[(low + 1) % fine.size] * part
        else:
            iq = np.fft.ifft(spectrum)[n % size]
        iq = iq * np.exp(2j * np.pi * self.cfo_hz / sample_rate_hz * n + 2j * np.pi * rng.random())
        iq = iq * self.level / np.sqrt(np.mean(np.abs(iq) ** 2))
        sigma = self.level * 10 ** (-self.snr_db / 20) / np.sqrt(2)
        iq = iq + sigma * (rng.normal(size=samples) + 1j * rng.normal(size=samples)) + self.dc
        return np.rint(iq.real) + 1j * np.rint(iq.imag) if self.quantize else iq
