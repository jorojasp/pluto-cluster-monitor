from __future__ import annotations

import argparse
import copy
import threading
import time
from typing import Any

from pluto_monitor.config.loader import load_config
from pluto_monitor.hardware.discovery import resolve_uri_from_serial
from pluto_monitor.hardware.transmitter import PlutoTransmitter, TransmitterConfig


VALID_MODES = {"SineWave", "BPSK", "QPSK", "16QAM"}


class LocalTxController:
    def __init__(self, config: dict[str, Any]):
        self.base_config = copy.deepcopy(config)
        self.active_config = copy.deepcopy(config)
        self.transmitter: PlutoTransmitter | None = None
        self.lock = threading.RLock()
        self.state = "idle"
        self.error: str | None = None

    def _resolve_uri(self, config: dict[str, Any]) -> str:
        radio = config["radio"]

        if radio.get("uri"):
            return str(radio["uri"])

        serial = radio.get("serial")
        if not serial:
            raise ValueError("TX radio needs either 'uri' or 'serial'")

        return resolve_uri_from_serial(str(serial).lower())

    def _runtime_config(
        self,
        app: dict[str, Any] | None,
        rf: dict[str, Any] | None,
    ) -> dict[str, Any]:
        config = copy.deepcopy(self.base_config)

        if app:
            for key in ("mode",):
                if key in app:
                    config["app"][key] = app[key]

        if rf:
            allowed = {
                "center_frequency_hz",
                "sample_rate_hz",
                "samples_per_frame",
                "tx_gain_db",
                "sps",
                "data_bits",
                "tone_frequency_hz",
            }

            for key, value in rf.items():
                if key in allowed:
                    config["rf"][key] = value

        self._validate(config)
        return config

    def _validate(self, config: dict[str, Any]) -> None:
        mode = str(config["app"]["mode"])
        rf = config["rf"]

        if mode not in VALID_MODES:
            raise ValueError(f"Unsupported TX mode: {mode}")

        if int(rf["center_frequency_hz"]) <= 0:
            raise ValueError("center_frequency_hz must be > 0")

        if int(rf["sample_rate_hz"]) <= 0:
            raise ValueError("sample_rate_hz must be > 0")

        if int(rf["samples_per_frame"]) < 2:
            raise ValueError("samples_per_frame must be >= 2")

        if float(rf["tx_gain_db"]) > 0:
            raise ValueError("tx_gain_db must be <= 0 dB")

        if int(rf.get("sps", 1)) < 1:
            raise ValueError("sps must be >= 1")

        if int(rf.get("data_bits", 1)) < 1:
            raise ValueError("data_bits must be >= 1")

    def _build_transmitter(
        self,
        config: dict[str, Any],
    ) -> PlutoTransmitter:
        rf = config["rf"]

        tx = PlutoTransmitter(
            TransmitterConfig(
                radio_id=self._resolve_uri(config),
                center_frequency_hz=int(rf["center_frequency_hz"]),
                sample_rate_hz=int(rf["sample_rate_hz"]),
                tx_gain_db=float(rf["tx_gain_db"]),
            )
        )

        tx.connect()
        return tx

    def _build_waveform(
        self,
        tx: PlutoTransmitter,
        config: dict[str, Any],
    ):
        mode = str(config["app"]["mode"])
        rf = config["rf"]

        if mode == "SineWave":
            return tx.build_tone(
                tone_frequency_hz=float(rf["tone_frequency_hz"]),
                num_samples=int(rf["samples_per_frame"]),
            )

        if mode == "BPSK":
            waveform, _, _ = tx.build_bpsk(
                data_bits=int(rf["data_bits"]),
                sps=int(rf["sps"]),
            )
            return waveform

        if mode == "QPSK":
            waveform, _, _ = tx.build_qpsk(
                data_bits=int(rf["data_bits"]),
                sps=int(rf["sps"]),
            )
            return waveform

        if mode == "16QAM":
            waveform, _, _ = tx.build_qam16(
                data_bits=int(rf["data_bits"]),
                sps=int(rf["sps"]),
            )
            return waveform

        raise ValueError(f"Unsupported TX mode: {mode}")

    def start(
        self,
        app: dict[str, Any] | None = None,
        rf: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            self.stop()

            try:
                config = self._runtime_config(app, rf)
                tx = self._build_transmitter(config)
                waveform = self._build_waveform(tx, config)

                tx.transmit_repeat(waveform)

                self.transmitter = tx
                self.active_config = config
                self.state = "running"
                self.error = None

                return self.status()

            except Exception as exc:
                self.state = "error"
                self.error = str(exc)

                if self.transmitter is not None:
                    self.transmitter.close()
                    self.transmitter = None

                raise

    def stop(self) -> dict[str, Any]:
        with self.lock:
            if self.transmitter is not None:
                try:
                    self.transmitter.close()
                finally:
                    self.transmitter = None

            self.state = "idle"
            self.error = None
            return self.status()

    def status(self) -> dict[str, Any]:
        rf = self.active_config.get("rf", {})
        app = self.active_config.get("app", {})

        return {
            "state": self.state,
            "mode": app.get("mode"),
            "center_frequency_hz": rf.get("center_frequency_hz"),
            "sample_rate_hz": rf.get("sample_rate_hz"),
            "tx_gain_db": rf.get("tx_gain_db"),
            "radio_uri": (
                self.transmitter.config.radio_id
                if self.transmitter is not None
                else None
            ),
            "error": self.error,
        }

    def close(self) -> None:
        self.stop()


def run(config_path: str) -> None:
    config = load_config(config_path)
    controller = LocalTxController(config)

    try:
        status = controller.start()
        print(
            f"TX running: mode={status['mode']} "
            f"fc={status['center_frequency_hz']} "
            f"gain={status['tx_gain_db']} dB"
        )

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        pass

    finally:
        controller.close()
        print("TX stopped")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)


if __name__ == "__main__":
    main()