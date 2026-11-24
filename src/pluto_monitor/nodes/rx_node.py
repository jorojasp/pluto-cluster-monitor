"""Receiver node: acquires local radios and reports metrics over UDP."""
from __future__ import annotations

import argparse
import copy
import math
import select
import socket
import time
from typing import Any

from pluto_monitor.config.loader import load_config
from pluto_monitor.config.runtime import apply_overrides
from pluto_monitor.hardware.discovery import resolve_uri_from_serial, scan_connected_radios
from pluto_monitor.hardware.factory import close_receivers, connect_receivers
from pluto_monitor.hardware.receiver import PlutoReceiver
from pluto_monitor.network.messages import dumps_message, loads_message
from pluto_monitor.network.udp_client import UdpJsonClient
from pluto_monitor.services.acquisition import (
    REPORTED,
    REPORTED_LISTS,
    AcquisitionResult,
    acquire_once,
)

MAX_CONSECUTIVE_ERRORS = 3
INVENTORY_PERIOD_S = 10.0
IDLE_POLL_S = 0.25


def _finite_or_none(value: Any) -> float | None:
    """Convert valid numeric values to float and NaN/inf to None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _radio_label(radio: dict[str, Any], index: int) -> str:
    return str(radio.get("label") or f"rx{index}")


def _resolve_radios(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map the URI of each configured radio to its label and serial."""
    metadata: dict[str, dict[str, Any]] = {}
    for index, radio in enumerate(config.get("radios", []), start=1):
        serial = str(radio["serial"]).lower() if radio.get("serial") else None
        if radio.get("uri"):
            uri = str(radio["uri"])
        elif serial:
            uri = resolve_uri_from_serial(serial)
        else:
            raise ValueError("Each RX radio needs either 'uri' or 'serial'")
        metadata[uri] = {"label": _radio_label(radio, index), "serial": serial, "uri": uri}
    if not metadata:
        raise ValueError("No RX radios configured under 'radios:'")
    return metadata


def _radio_inventory(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Discover attached devices, also while acquisition is idle."""
    try:
        discovered = scan_connected_radios()
    except Exception as exc:
        print(f"Radio discovery failed: {exc}")
        discovered = None

    radios = []
    for index, radio in enumerate(config.get("radios", []), start=1):
        serial = str(radio.get("serial") or "").lower()
        uri = radio.get("uri")
        match = next(
            (
                item
                for item in (discovered or [])
                if (serial and item["serial"] == serial)
                or (not serial and uri and item["uri"] == uri)
            ),
            None,
        )
        radios.append({
            "label": _radio_label(radio, index),
            "serial": serial or (match["serial"] if match else None),
            "uri": match["uri"] if match else uri,
            "connected": match is not None if discovered is not None else None,
        })
    return radios


def _node_message(message_type: str, config: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {
        "type": message_type,
        "node_id": str(config["node"]["id"]),
        "role": "receiver",
        "group": str(config["node"]["group"]),
        "timestamp": time.time(),
        **fields,
    }


def _build_status_message(
    *,
    config: dict[str, Any],
    state: str,
    connected_radios: int,
    radios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _node_message(
        "rx_status", config, state=state, connected_radios=connected_radios, radios=radios or []
    )


def _result_to_message(
    *,
    config: dict[str, Any],
    result: AcquisitionResult,
    group: str,
    metadata_by_uri: dict[str, dict[str, Any]],
    sequence: int,
) -> dict[str, Any]:
    radios = []
    for uri, metrics in result.group_metrics[group].items():
        meta = metadata_by_uri[uri]
        radios.append({
            "label": meta["label"],
            "serial": meta["serial"],
            "uri": uri,
            **{
                key: _finite_or_none(metrics.get(key))
                for key in REPORTED
            },
            **{key: metrics[key] for key in REPORTED_LISTS if key in metrics},
        })

    valid = [radio for radio in radios if radio["power_db"] is not None]
    strongest = max(valid, key=lambda r: r["power_db"], default=None)
    weakest = min(valid, key=lambda r: r["power_db"], default=None)

    return _node_message(
        "rx_metrics",
        config,
        sequence=sequence,
        rf=copy.deepcopy(config["rf"]),
        timestamp=result.timestamp,
        mode=str(config["app"]["mode"]),
        radios=radios,
        summary={
            "strongest_label": strongest["label"] if strongest else None,
            "strongest_db": strongest["power_db"] if strongest else None,
            "weakest_label": weakest["label"] if weakest else None,
            "weakest_db": weakest["power_db"] if weakest else None,
            "mean_power_db": _finite_or_none(result.group_mean_power_db.get(group)),
            "mean_noise_db": _finite_or_none(result.group_mean_noise_db.get(group)),
        },
    )


class RxNode:
    def __init__(self, config: dict[str, Any]) -> None:
        self.base_config = config
        self.active_config = copy.deepcopy(config)
        self.node_id = str(config["node"]["id"])
        self.group = str(config["node"]["group"])

        net = config["network"]
        self.metrics_client = UdpJsonClient(
            host=str(net["central_host"]),
            port=int(net.get("metrics_port", net.get("central_port", 5555))),
        )
        self.control_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.control_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.control_sock.bind(
            (str(net.get("control_host", "0.0.0.0")), int(net.get("control_port", 5556)))
        )
        self.control_sock.setblocking(False)
        self.heartbeat_period_s = float(net.get("heartbeat_period_s", 2.0))

        self.receivers: dict[str, PlutoReceiver] = {}
        self.metadata_by_uri: dict[str, dict[str, Any]] = {}
        self.inventory: list[dict[str, Any]] = []
        self.running = False
        self.sequence = 0
        self.consecutive_errors = 0
        self.next_acquisition = 0.0
        self.next_heartbeat = 0.0
        self.next_inventory = 0.0

    @property
    def state(self) -> str:
        return "running" if self.running else "idle"

    # ---- network ----------------------------------------------------------

    def _send(self, message: dict[str, Any]) -> None:
        """Report to the server; a network failure must not end the process."""
        try:
            self.metrics_client.send(message)
        except OSError as exc:
            print(f"Cannot reach the server: {exc}")

    def _respond(
        self, addr: tuple[str, int], command: str, state: str, error: str | None = None
    ) -> None:
        response = {
            "type": "rx_command_response",
            "command": command,
            "node_id": self.node_id,
            "success": error is None,
            "state": state,
            "timestamp": time.time(),
        }
        if error is not None:
            response["error"] = error
        try:
            self.control_sock.sendto(dumps_message(response), addr)
        except OSError as exc:
            print(f"Cannot answer {addr}: {exc}")

    # ---- commands ---------------------------------------------------------

    def _start(self, command: dict[str, Any], addr: tuple[str, int]) -> None:
        self._stop_acquisition()
        try:
            # Radio serials stay local; the server only changes app/RF settings.
            self.active_config = apply_overrides(
                self.base_config, command.get("app"), command.get("rf")
            )
            self.metadata_by_uri = _resolve_radios(self.active_config)
            self.receivers = connect_receivers(list(self.metadata_by_uri), self.active_config)
        except Exception as exc:
            print(f"START failed: {exc}")
            self._respond(addr, "start", "error", str(exc))
            self._send(_node_message("rx_error", self.base_config, error=str(exc)))
            return

        self.running = True
        self.sequence = 0
        self.consecutive_errors = 0
        self.next_acquisition = time.monotonic()
        app, rf = self.active_config["app"], self.active_config["rf"]
        print(
            f"START from {addr[0]}: {app['mode']}, {rf['center_frequency_hz']} Hz, "
            f"{rf['sample_rate_hz']} S/s, RX gain {rf['rx_gain_db']} dB"
        )
        self._respond(addr, "start", "running")

    def _stop_acquisition(self) -> None:
        self.running = False
        close_receivers(self.receivers)
        self.metadata_by_uri = {}

    def _handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            message = loads_message(data)
        except ValueError as exc:
            print(f"Invalid command from {addr}: {exc}")
            return
        if message.get("type") != "rx_command":
            return

        command = str(message.get("command", "")).lower()
        if command == "start":
            self._start(message, addr)
        elif command == "stop":
            self._stop_acquisition()
            print(f"STOP from {addr[0]}")
            self._respond(addr, "stop", "idle")
        else:
            self._respond(addr, command, self.state, "Unknown command")

    def _poll_commands(self) -> None:
        timeout = IDLE_POLL_S
        if self.running:
            timeout = max(0.0, min(timeout, self.next_acquisition - time.monotonic()))
        readable, _, _ = select.select([self.control_sock], [], [], timeout)
        while readable:
            try:
                data, addr = self.control_sock.recvfrom(65535)
            except OSError:  # nothing left, or an ICMP error on Windows
                return
            self._handle_datagram(data, addr)

    # ---- periodic work ----------------------------------------------------

    def _heartbeat(self) -> None:
        now = time.monotonic()
        if now < self.next_heartbeat:
            return
        if now >= self.next_inventory:
            self.inventory = _radio_inventory(self.base_config)
            self.next_inventory = time.monotonic() + INVENTORY_PERIOD_S
        self._send(_build_status_message(
            config=self.base_config,
            state=self.state,
            connected_radios=sum(radio["connected"] is True for radio in self.inventory),
            radios=self.inventory,
        ))
        self.next_heartbeat = now + self.heartbeat_period_s

    def _acquire(self) -> None:
        if not self.running or time.monotonic() < self.next_acquisition:
            return
        started = time.monotonic()
        try:
            result = acquire_once(
                groups={self.group: {"radio_ids": list(self.receivers)}},
                receivers=self.receivers,
                mode=str(self.active_config["app"]["mode"]),
                rf_config=self.active_config["rf"],
            )
            message = _result_to_message(
                config=self.active_config,
                result=result,
                group=self.group,
                metadata_by_uri=self.metadata_by_uri,
                sequence=self.sequence + 1,
            )
        except Exception as exc:
            self._acquisition_failed(exc)
        else:
            self.sequence += 1
            self.consecutive_errors = 0
            self._send(message)
            summary = message["summary"]
            print(
                f"\rseq={self.sequence:<6} group={self.group} "
                f"strongest={summary['strongest_label'] or '---':<8} "
                f"weakest={summary['weakest_label'] or '---':<8}",
                end="",
                flush=True,
            )
        period = float(self.active_config["app"]["update_period_s"])
        self.next_acquisition = max(time.monotonic(), started + period)

    def _acquisition_failed(self, exc: Exception) -> None:
        self.consecutive_errors += 1
        print(f"\nAcquisition error ({self.consecutive_errors}): {exc}")
        self._send(_node_message("rx_error", self.base_config, error=str(exc)))
        if self.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            print("Too many consecutive acquisition errors. Returning to idle.")
            self._stop_acquisition()

    # ---- lifecycle --------------------------------------------------------

    def step(self) -> None:
        self._poll_commands()
        self._heartbeat()
        self._acquire()

    def close(self) -> None:
        self._stop_acquisition()
        self.control_sock.close()
        self.metrics_client.close()


def run(config_path: str) -> None:
    node = RxNode(load_config(config_path))
    print(f"RX node {node.node_id} (group {node.group}) idle, waiting for START")
    try:
        while True:
            node.step()
    except KeyboardInterrupt:
        print("\nStopping RX node...")
    finally:
        node.close()
        print("RX node stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Raspberry Pi Pluto receiver node")
    parser.add_argument("--config", required=True, help="Path to RX node YAML configuration")
    run(parser.parse_args().config)


if __name__ == "__main__":
    main()
