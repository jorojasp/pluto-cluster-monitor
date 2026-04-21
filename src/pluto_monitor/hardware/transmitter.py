from __future__ import annotations

from dataclasses import dataclass
from pluto_monitor.dsp.bpsk import build_bpsk_tx_waveform

import numpy as np


@dataclass
class TransmitterConfig:
    radio_id: str
    center_frequency_hz: int
    sample_rate_hz: int
    tx_gain_db: float

class PlutoTransmitter:
    def __init__(self, config: TransmitterConfig) -> None:
        self.config = config
        self._device = None

    def connect(self) -> None:
        import adi

        sdr = adi.Pluto(self.config.radio_id)
        sdr.tx_lo = int(self.config.center_frequency_hz)
        sdr.sample_rate = int(self.config.sample_rate_hz)
        sdr.tx_hardwaregain_chan0 = float(self.config.tx_gain_db)
        sdr.tx_cyclic_buffer = True
        self._device = sdr

    def transmit_repeat(self, samples: np.ndarray) -> None:
        if self._device is None:
            raise RuntimeError(
                f"Transmitter {self.config.radio_id} is not connected"
            )

        iq = np.asarray(samples, dtype=np.complex64)
        if iq.size == 0:
            raise ValueError("Cannot transmit an empty waveform")

        peak = np.max(np.abs(iq))
        if peak > 0:
            iq = iq / peak

        self._device.tx_destroy_buffer()
        self._device.tx(iq)

    def build_tone(self,
        tone_frequency_hz: float,
        num_samples: int,
    ) -> np.ndarray:
        sample_rate = self.config.sample_rate_hz
        t = np.arange(num_samples, dtype=np.float64) / sample_rate
        tone = np.exp(1j * 2.0 * np.pi * tone_frequency_hz * t)
        return tone.astype(np.complex64)
    
    def build_bpsk(
        self,
        data_bits: int,
        sps: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        tx_waveform, tx_bits, tx_symbols = build_bpsk_tx_waveform(
            data_bits=data_bits,
            sps=sps,
        )
        return tx_waveform, tx_bits, tx_symbols

    def stop(self) -> None:
        if self._device is None:
            return

        try:
            self._device.tx_destroy_buffer()
        except Exception:
            pass

    def close(self) -> None:
        self.stop()
        self._device = None