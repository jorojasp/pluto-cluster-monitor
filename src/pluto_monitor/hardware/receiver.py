import time
from dataclasses import dataclass

import numpy as np

QUEUED_BUFFERS = 4  # libiio default
SETTLE_S = 0.1


@dataclass
class ReceiverConfig:
    radio_id: str
    center_frequency_hz: int
    sample_rate_hz: int
    samples_per_frame: int
    rx_gain_db: float
    rf_bandwidth_hz: int | None = None  # defaults to the sample rate


def analog_bandwidth(requested_hz: int | None, sample_rate_hz: int) -> int:
    """Analog filter bandwidth, limited to the AD9363 range.

    Left unset, the radio keeps its 18 MHz default and lets strong
    out-of-band signals such as Wi-Fi reach the ADC.
    """
    return int(min(max(requested_hz or sample_rate_hz, 200_000), 20_000_000))


class PlutoReceiver:
    def __init__(self, config: ReceiverConfig) -> None:
        self.config = config
        self._device = None

    def connect(self) -> None:
        import adi

        sdr = adi.Pluto(self.config.radio_id)
        sdr.rx_lo = int(self.config.center_frequency_hz)
        sdr.sample_rate = int(self.config.sample_rate_hz)
        sdr.rx_rf_bandwidth = analog_bandwidth(
            self.config.rf_bandwidth_hz, self.config.sample_rate_hz
        )
        sdr.rx_buffer_size = int(self.config.samples_per_frame)
        sdr.gain_control_mode_chan0 = "manual"
        sdr.rx_hardwaregain_chan0 = float(self.config.rx_gain_db)
        # The first samples carry a strong DC transient (about 20 ms).
        sdr.rx()
        time.sleep(SETTLE_S)
        self._device = sdr

    def read_samples(self) -> np.ndarray:
        if self._device is None:
            raise RuntimeError(
                f"Receiver {self.config.radio_id} is not connected"
            )
        # The radio keeps filling a short queue between calls, so the oldest
        # buffers can be seconds old. Drop them and return a recent capture.
        for _ in range(QUEUED_BUFFERS):
            self._device.rx()
        data = self._device.rx()
        return np.asarray(data, dtype=np.complex128)

    def close(self) -> None:
        if self._device is not None:
            try:
                self._device.rx_destroy_buffer()
            finally:
                self._device = None
