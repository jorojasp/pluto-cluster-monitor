from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pluto_monitor.hardware.receiver import analog_bandwidth


@dataclass
class TransmitterConfig:
    radio_id: str
    center_frequency_hz: int
    sample_rate_hz: int
    tx_gain_db: float
    rf_bandwidth_hz: int | None = None  # defaults to the sample rate


class PlutoTransmitter:
    def __init__(self, config: TransmitterConfig) -> None:
        self.config = config
        self._device = None

    def connect(self) -> None:
        import adi

        sdr = adi.Pluto(self.config.radio_id)
        sdr.tx_lo = int(self.config.center_frequency_hz)
        sdr.sample_rate = int(self.config.sample_rate_hz)
        sdr.tx_rf_bandwidth = analog_bandwidth(
            self.config.rf_bandwidth_hz, self.config.sample_rate_hz
        )
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

        if not np.all(np.isfinite(iq)):
            raise ValueError("TX samples must be finite")
        rms = float(np.sqrt(np.mean(np.abs(iq.astype(np.complex128)) ** 2)))
        if rms <= 0:
            raise ValueError("Cannot transmit a zero-power waveform")
        # pyadi-iio expects DAC codes, not normalized floating-point samples.
        # Equal RMS keeps the average digital drive comparable across modes.
        iq = iq * ((2 ** 13) / rms)
        peak = float(np.max(np.abs(iq)))
        if peak > 2 ** 14:
            iq *= (2 ** 14) / peak
        iq = (np.rint(iq.real) + 1j * np.rint(iq.imag)).astype(np.complex64)

        self._device.tx_destroy_buffer()
        self._device.tx(iq)

    def stop(self) -> None:
        if self._device is None:
            return

        try:
            self._device.tx_destroy_buffer()
        except Exception as exc:
            print(f"Could not stop transmitter {self.config.radio_id}: {exc}")

    def close(self) -> None:
        self.stop()
        self._device = None
