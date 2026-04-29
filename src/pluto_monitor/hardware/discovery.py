from __future__ import annotations

import re
from dataclasses import dataclass

import iio


SERIAL_RE = re.compile(r"serial=([A-Za-z0-9]+)")


@dataclass(frozen=True)
class RadioTopology:
    receiver_serials: list[str]
    transmitter_serial: str


@dataclass(frozen=True)
class ResolvedRadioTopology:
    receiver_uris: list[str]
    transmitter_uri: str
    serial_to_uri: dict[str, str]


def _extract_serial(description: str) -> str:
    match = SERIAL_RE.search(description)
    if not match:
        return ""
    return match.group(1).lower()


def _uri_priority(uri: str) -> tuple[int, str]:
    uri_lower = uri.lower()

    if uri_lower.startswith("usb:"):
        return (0, uri_lower)
    if uri_lower.startswith("ip:"):
        return (1, uri_lower)
    return (2, uri_lower)


def scan_connected_radios() -> list[dict[str, str]]:
    contexts = iio.scan_contexts()
    radios: list[dict[str, str]] = []

    for uri, description in contexts.items():
        radios.append(
            {
                "uri": uri,
                "description": description,
                "serial": _extract_serial(description),
            }
        )

    return radios


def get_required_topology(config: dict) -> RadioTopology:
    groups = config["clusters"]["groups"]
    tx_serial = config["clusters"]["transmitter_serial"]

    receiver_serials: list[str] = []
    for group_data in groups.values():
        receiver_serials.extend(
            [serial.lower() for serial in group_data["radio_serials"]]
        )

    tx_serial = tx_serial.lower()

    if not receiver_serials:
        raise ValueError("No receiver radios configured")

    if not tx_serial:
        raise ValueError("Missing transmitter serial")

    if tx_serial in receiver_serials:
        raise ValueError(
            f"Transmitter serial {tx_serial} is also listed as a receiver"
        )

    if len(receiver_serials) != len(set(receiver_serials)):
        raise ValueError("Duplicate receiver serials found in configuration")

    return RadioTopology(
        receiver_serials=receiver_serials,
        transmitter_serial=tx_serial,
    )


def discover_configured_radios(config: dict) -> list[dict[str, str]]:
    return scan_connected_radios()


def resolve_uri_from_serial(target_serial: str) -> str:
    target_serial = target_serial.lower()
    radios = scan_connected_radios()

    matches = [radio for radio in radios if radio["serial"] == target_serial]

    if not matches:
        available_serials = sorted(
            {radio["serial"] for radio in radios if radio["serial"]}
        )
        raise RuntimeError(
            f"Could not find a connected Pluto with serial '{target_serial}'. "
            f"Available serials: {available_serials}"
        )

    best_match = min(matches, key=lambda radio: _uri_priority(radio["uri"]))
    return best_match["uri"]


def resolve_topology(config: dict) -> ResolvedRadioTopology:
    topology = get_required_topology(config)

    serial_to_uri: dict[str, str] = {}

    for serial in topology.receiver_serials:
        serial_to_uri[serial] = resolve_uri_from_serial(serial)

    serial_to_uri[topology.transmitter_serial] = resolve_uri_from_serial(
        topology.transmitter_serial
    )

    receiver_uris = [serial_to_uri[s] for s in topology.receiver_serials]
    transmitter_uri = serial_to_uri[topology.transmitter_serial]

    return ResolvedRadioTopology(
        receiver_uris=receiver_uris,
        transmitter_uri=transmitter_uri,
        serial_to_uri=serial_to_uri,
    )


def validate_required_radios(config: dict) -> None:
    topology = get_required_topology(config)
    connected_radios = scan_connected_radios()

    connected_serials = {
        radio["serial"].lower()
        for radio in connected_radios
        if radio["serial"]
    }

    required_serials = set(topology.receiver_serials) | {topology.transmitter_serial}
    missing_serials = required_serials - connected_serials

    if missing_serials:
        raise RuntimeError(
            f"Missing required Pluto radios with serials: {sorted(missing_serials)}. "
            f"Connected serials: {sorted(connected_serials)}"
        )