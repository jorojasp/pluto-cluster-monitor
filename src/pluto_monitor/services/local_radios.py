"""Radios attached to this PC, as described by the `clusters` configuration."""
from __future__ import annotations

from typing import Any

from pluto_monitor.hardware.discovery import ResolvedRadioTopology
from pluto_monitor.hardware.factory import (
    connect_receivers,
    connect_transmitter,
    start_transmission,
)
from pluto_monitor.hardware.receiver import PlutoReceiver
from pluto_monitor.hardware.transmitter import PlutoTransmitter


def build_receivers(
    config: dict[str, Any], resolved: ResolvedRadioTopology
) -> tuple[dict[str, PlutoReceiver], dict[str, list[str]]]:
    """Return connected receivers by URI and the URIs of each group."""
    groups = {
        name: [resolved.serial_to_uri[serial.lower()] for serial in data["radio_serials"]]
        for name, data in config["clusters"]["groups"].items()
    }
    uris = [uri for group in groups.values() for uri in group]
    return connect_receivers(uris, config), groups


def build_transmitter(
    config: dict[str, Any], resolved: ResolvedRadioTopology
) -> PlutoTransmitter | None:
    """Start transmitting, or return None when app.transmit_enabled is false."""
    if not config["app"].get("transmit_enabled", True):
        return None
    transmitter = connect_transmitter(resolved.transmitter_uri, config)
    try:
        start_transmission(transmitter, config)
    except Exception:
        transmitter.close()
        raise
    return transmitter
