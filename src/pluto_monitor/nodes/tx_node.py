from __future__ import annotations

import argparse
import copy
import threading
import time
from typing import Any

from pluto_monitor.config.loader import load_config
from pluto_monitor.config.runtime import apply_overrides
from pluto_monitor.hardware.discovery import resolve_uri_from_serial
from pluto_monitor.hardware.factory import connect_transmitter, start_transmission
from pluto_monitor.hardware.transmitter import PlutoTransmitter


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

    def start(
        self,
        app: dict[str, Any] | None = None,
        rf: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            self.stop()

            try:
                config = apply_overrides(self.base_config, app, rf)
                self.transmitter = connect_transmitter(self._resolve_uri(config), config)
                start_transmission(self.transmitter, config)

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
