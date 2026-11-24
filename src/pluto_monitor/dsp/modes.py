"""Registry of transmission modes.

A mode knows how to build its cyclic TX waveform, how many samples a receiver
must capture, and how to measure a capture. The rest of the application only
uses this interface, so a new mode is added here and nowhere else.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import numpy as np

from pluto_monitor.dsp import ofdm, single_carrier
from pluto_monitor.dsp.sinewave import build_tone, compute_sinewave_detailed_metrics


class Mode(Protocol):
    name: str
    # Interface control group shown for this mode: "tone", "digital" or "ofdm".
    controls: str

    def validate(self, rf: dict[str, Any]) -> None: ...
    def build_waveform(self, rf: dict[str, Any]) -> np.ndarray: ...
    def capture_samples(self, rf: dict[str, Any]) -> int: ...
    def measure(self, iq: np.ndarray, rf: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SineWaveMode:
    name: str = "SineWave"
    controls: str = "tone"

    def validate(self, rf: dict[str, Any]) -> None:
        if abs(float(rf["tone_frequency_hz"])) >= float(rf["sample_rate_hz"]) / 2:
            raise ValueError("tone_frequency_hz must be below half the sample rate")

    def build_waveform(self, rf: dict[str, Any]) -> np.ndarray:
        return build_tone(
            float(rf["tone_frequency_hz"]),
            float(rf["sample_rate_hz"]),
            int(rf["samples_per_frame"]),
        )

    def capture_samples(self, rf: dict[str, Any]) -> int:
        return int(rf["samples_per_frame"])

    def measure(self, iq: np.ndarray, rf: dict[str, Any]) -> dict[str, float]:
        return compute_sinewave_detailed_metrics(
            iq,
            sample_rate_hz=float(rf["sample_rate_hz"]),
            tone_frequency_hz=float(rf["tone_frequency_hz"]),
        )


@dataclass(frozen=True)
class SingleCarrierMode:
    modulation: single_carrier.Modulation
    controls: str = "digital"

    @property
    def name(self) -> str:
        return self.modulation.name

    def validate(self, rf: dict[str, Any]) -> None:
        if int(rf["sps"]) < 2:
            raise ValueError("sps must be >= 2 for digital modes")
        single_carrier.frame_samples(self.modulation, int(rf["data_bits"]), int(rf["sps"]))

    def build_waveform(self, rf: dict[str, Any]) -> np.ndarray:
        return single_carrier.build_waveform(
            self.modulation, int(rf["data_bits"]), int(rf["sps"])
        )[0]

    def capture_samples(self, rf: dict[str, Any]) -> int:
        # Two frames always contain a complete one, wherever the capture starts.
        frame = single_carrier.frame_samples(
            self.modulation, int(rf["data_bits"]), int(rf["sps"])
        )
        return max(int(rf["samples_per_frame"]), 2 * frame + 16)

    def measure(self, iq: np.ndarray, rf: dict[str, Any]) -> dict[str, float]:
        return single_carrier.analyze(
            self.modulation,
            iq,
            float(rf["sample_rate_hz"]),
            int(rf["data_bits"]),
            int(rf["sps"]),
        )


# Viterbi decoding time grows with the payload.
MAX_OFDM_BITS = 16_384


@lru_cache(maxsize=8)
def ofdm_frame(modulation: single_carrier.Modulation, data_bits: int) -> ofdm.OfdmFrame:
    return ofdm.OfdmFrame(modulation, data_bits)


@dataclass(frozen=True)
class OfdmMode:
    modulation: single_carrier.Modulation
    controls: str = "ofdm"

    @property
    def name(self) -> str:
        return f"OFDM-{self.modulation.name}"

    def _frame(self, rf: dict[str, Any]) -> ofdm.OfdmFrame:
        return ofdm_frame(self.modulation, int(rf["data_bits"]))

    def validate(self, rf: dict[str, Any]) -> None:
        bits = int(rf["data_bits"])
        if bits % 8 or not 8 <= bits <= MAX_OFDM_BITS:
            raise ValueError(f"data_bits must be a multiple of 8 up to {MAX_OFDM_BITS} for OFDM")

    def build_waveform(self, rf: dict[str, Any]) -> np.ndarray:
        return self._frame(rf).waveform()

    def capture_samples(self, rf: dict[str, Any]) -> int:
        return max(int(rf["samples_per_frame"]), 2 * self._frame(rf).samples + 16)

    def measure(self, iq: np.ndarray, rf: dict[str, Any]) -> dict[str, Any]:
        return ofdm.analyze(self._frame(rf), iq, float(rf["sample_rate_hz"]))


MODES: dict[str, Mode] = {
    mode.name: mode
    for mode in (
        SineWaveMode(),
        SingleCarrierMode(single_carrier.BPSK),
        SingleCarrierMode(single_carrier.QPSK),
        SingleCarrierMode(single_carrier.QAM16),
        OfdmMode(single_carrier.QPSK),
        OfdmMode(single_carrier.QAM16),
    )
}


def get_mode(name: str) -> Mode:
    try:
        return MODES[str(name)]
    except KeyError:
        raise ValueError(f"Unsupported mode '{name}'. Valid modes: {sorted(MODES)}") from None
