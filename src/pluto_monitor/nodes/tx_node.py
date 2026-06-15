from __future__ import annotations

import argparse
import time
from typing import Any

from pluto_monitor.config.loader import load_config
from pluto_monitor.hardware.discovery import resolve_uri_from_serial
from pluto_monitor.hardware.transmitter import PlutoTransmitter, TransmitterConfig


def _resolve_tx_uri(config: dict[str, Any]) -> str:
    radio_cfg = config["radio"]
    if radio_cfg.get("uri"):
        return str(radio_cfg["uri"])
    if not radio_cfg.get("serial"):
        raise ValueError("TX radio needs either 'uri' or 'serial'")
    return resolve_uri_from_serial(str(radio_cfg["serial"]).lower())


def _build_transmitter(config: dict[str, Any]) -> PlutoTransmitter:
    rf = config["rf"]
    tx_uri = _resolve_tx_uri(config)
    tx_cfg = TransmitterConfig(
        radio_id=tx_uri,
        center_frequency_hz=int(rf["center_frequency_hz"]),
        sample_rate_hz=int(rf["sample_rate_hz"]),
        tx_gain_db=float(rf["tx_gain_db"]),
    )
    tx = PlutoTransmitter(tx_cfg)
    tx.connect()
    return tx


def _start_waveform(tx: PlutoTransmitter, config: dict[str, Any]) -> None:
    mode = str(config["app"]["mode"])
    rf = config["rf"]

    if mode == "SineWave":
        waveform = tx.build_tone(
            tone_frequency_hz=float(rf["tone_frequency_hz"]),
            num_samples=int(rf["samples_per_frame"]),
        )
    elif mode == "BPSK":
        waveform, _, _ = tx.build_bpsk(
            data_bits=int(rf["data_bits"]),
            sps=int(rf["sps"]),
        )
    elif mode == "QPSK":
        waveform, _, _ = tx.build_qpsk(
            data_bits=int(rf["data_bits"]),
            sps=int(rf["sps"]),
        )
    elif mode == "16QAM":
        waveform, _, _ = tx.build_qam16(
            data_bits=int(rf["data_bits"]),
            sps=int(rf["sps"]),
        )
    else:
        raise NotImplementedError(f"Unsupported TX mode: {mode}")

    tx.transmit_repeat(waveform)
    print(f"TX started: mode={mode}, samples={len(waveform)}, uri={tx.config.radio_id}")


def run(config_path: str) -> None:
    config = load_config(config_path)
    transmitter: PlutoTransmitter | None = None

    try:
        transmitter = _build_transmitter(config)
        _start_waveform(transmitter, config)
        print("TX node running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Stopping TX node...")
    finally:
        if transmitter is not None:
            transmitter.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Raspberry Pi transmitter node")
    parser.add_argument("--config", required=True, help="Path to TX node YAML config")
    args = parser.parse_args()
    run(args.config)


if __name__ == "__main__":
    main()
