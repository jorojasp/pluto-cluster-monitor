"""Create connected radios from a runtime configuration."""
from __future__ import annotations

from typing import Any

from pluto_monitor.dsp.modes import get_mode
from pluto_monitor.hardware.receiver import PlutoReceiver, ReceiverConfig
from pluto_monitor.hardware.transmitter import PlutoTransmitter, TransmitterConfig


def connect_receivers(uris: list[str], config: dict[str, Any]) -> dict[str, PlutoReceiver]:
    """Connect every receiver, or none: a failure closes those already open."""
    rf = config["rf"]
    samples = get_mode(config["app"]["mode"]).capture_samples(rf)
    receivers: dict[str, PlutoReceiver] = {}
    try:
        for uri in uris:
            receiver = PlutoReceiver(
                ReceiverConfig(
                    radio_id=uri,
                    center_frequency_hz=int(rf["center_frequency_hz"]),
                    sample_rate_hz=int(rf["sample_rate_hz"]),
                    samples_per_frame=samples,
                    rx_gain_db=float(rf["rx_gain_db"]),
                    rf_bandwidth_hz=rf.get("rf_bandwidth_hz"),
                )
            )
            receiver.connect()
            receivers[uri] = receiver
    except Exception:
        close_receivers(receivers)
        raise
    return receivers


def close_receivers(receivers: dict[str, PlutoReceiver]) -> None:
    for uri, receiver in receivers.items():
        try:
            receiver.close()
        except Exception as exc:  # a vanished radio must not block the others
            print(f"Warning while closing receiver {uri}: {exc}")
    receivers.clear()


def connect_transmitter(uri: str, config: dict[str, Any]) -> PlutoTransmitter:
    rf = config["rf"]
    transmitter = PlutoTransmitter(
        TransmitterConfig(
            radio_id=uri,
            center_frequency_hz=int(rf["center_frequency_hz"]),
            sample_rate_hz=int(rf["sample_rate_hz"]),
            tx_gain_db=float(rf["tx_gain_db"]),
            rf_bandwidth_hz=rf.get("rf_bandwidth_hz"),
        )
    )
    transmitter.connect()
    return transmitter


def start_transmission(transmitter: PlutoTransmitter, config: dict[str, Any]) -> None:
    """Build the waveform of the configured mode and repeat it."""
    waveform = get_mode(config["app"]["mode"]).build_waveform(config["rf"])
    transmitter.transmit_repeat(waveform)
