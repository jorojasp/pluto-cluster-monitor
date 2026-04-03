from dataclasses import dataclass

import numpy as np


@dataclass
class ReceiverConfig:
    radio_id: str
    center_frequency_hz: int
    sample_rate_hz: int
    samples_per_frame: int
    rx_gain_db: float


class PlutoReceiver:
    def __init__(self, config: ReceiverConfig) -> None:
        self.config = config
        self._device = None

    def connect(self) -> None:
        import adi

        sdr = adi.Pluto(self.config.radio_id)
        sdr.rx_lo = int(self.config.center_frequency_hz)
        sdr.sample_rate = int(self.config.sample_rate_hz)
        sdr.rx_buffer_size = int(self.config.samples_per_frame)
        sdr.gain_control_mode_chan0 = "manual"
        sdr.rx_hardwaregain_chan0 = float(self.config.rx_gain_db)
        self._device = sdr

    def read_samples(self) -> np.ndarray:
        if self._device is None:
            raise RuntimeError(
                f"Receiver {self.config.radio_id} is not connected"
            )
        data = self._device.rx()
        return np.asarray(data, dtype=np.complex128)

    def close(self) -> None:
        self._device = None