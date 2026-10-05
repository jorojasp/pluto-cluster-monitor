from __future__ import annotations

import argparse
import copy
import math
import select
import socket
import time
from typing import Any

from pluto_monitor.config.loader import load_config
from pluto_monitor.hardware.discovery import resolve_uri_from_serial
from pluto_monitor.hardware.receiver import PlutoReceiver, ReceiverConfig
from pluto_monitor.network.messages import dumps_message, loads_message
from pluto_monitor.network.udp_client import UdpJsonClient
from pluto_monitor.services.acquisition import acquire_once


VALID_MODES = {
    "SineWave",
    "BPSK",
    "QPSK",
    "16QAM",
}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _finite_or_none(value: Any) -> float | None:
    """Convert valid numeric values to float and NaN/inf to None."""
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number):
        return None

    return number


def _resolve_radio_uri(
    radio_cfg: dict[str, Any],
) -> tuple[str, str | None]:
    """
    Return (uri, serial).

    A radio may be configured either with:
        uri: usb:...
    or:
        serial: ...
    """

    if radio_cfg.get("uri"):
        return (
            str(radio_cfg["uri"]),
            radio_cfg.get("serial"),
        )

    serial = radio_cfg.get("serial")

    if not serial:
        raise ValueError(
            "Each RX radio needs either 'uri' or 'serial'"
        )

    serial = str(serial).lower()

    uri = resolve_uri_from_serial(serial)

    return uri, serial


# ---------------------------------------------------------------------
# Receiver creation
# ---------------------------------------------------------------------

def _build_receivers(
    config: dict[str, Any],
) -> tuple[
    dict[str, PlutoReceiver],
    dict[str, dict[str, Any]],
]:
    """
    Build and connect all Pluto receivers physically connected
    to this Raspberry Pi.
    """

    rf = config["rf"]

    receivers: dict[str, PlutoReceiver] = {}
    metadata_by_uri: dict[str, dict[str, Any]] = {}

    for idx, radio_cfg in enumerate(
        config.get("radios", []),
        start=1,
    ):
        uri, serial = _resolve_radio_uri(radio_cfg)

        label = str(
            radio_cfg.get("label")
            or f"rx{idx}"
        )

        rx_cfg = ReceiverConfig(
            radio_id=uri,
            center_frequency_hz=int(
                rf["center_frequency_hz"]
            ),
            sample_rate_hz=int(
                rf["sample_rate_hz"]
            ),
            samples_per_frame=int(
                rf["samples_per_frame"]
            ),
            rx_gain_db=float(
                rf["rx_gain_db"]
            ),
        )

        receiver = PlutoReceiver(rx_cfg)

        print(
            f"Connecting {label}: "
            f"{uri} serial={serial}"
        )

        receiver.connect()

        receivers[uri] = receiver

        metadata_by_uri[uri] = {
            "label": label,
            "serial": serial,
            "uri": uri,
        }

    if not receivers:
        raise ValueError(
            "No RX radios configured under 'radios:'"
        )

    return receivers, metadata_by_uri


def _close_receivers(
    receivers: dict[str, PlutoReceiver],
) -> None:
    for receiver in receivers.values():
        try:
            receiver.close()
        except Exception as exc:
            print(
                f"Warning while closing receiver: {exc}"
            )

    receivers.clear()


# ---------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------

def _validate_runtime_config(
    config: dict[str, Any],
) -> None:
    app = config["app"]
    rf = config["rf"]

    mode = str(app["mode"])

    if mode not in VALID_MODES:
        raise ValueError(
            f"Unsupported mode: {mode}"
        )

    if float(app["update_period_s"]) <= 0:
        raise ValueError(
            "update_period_s must be > 0"
        )

    if int(rf["center_frequency_hz"]) <= 0:
        raise ValueError(
            "center_frequency_hz must be > 0"
        )

    if int(rf["sample_rate_hz"]) <= 0:
        raise ValueError(
            "sample_rate_hz must be > 0"
        )

    if int(rf["samples_per_frame"]) < 2:
        raise ValueError(
            "samples_per_frame must be >= 2"
        )

    if int(rf.get("sps", 1)) < 1:
        raise ValueError(
            "sps must be >= 1"
        )

    if int(rf.get("data_bits", 1)) < 1:
        raise ValueError(
            "data_bits must be >= 1"
        )


def _build_runtime_config(
    base_config: dict[str, Any],
    command: dict[str, Any],
) -> dict[str, Any]:
    """
    Build the acquisition configuration for a START command.

    Important:
    - Radio serials remain LOCAL to each Raspberry Pi.
    - The central server is only allowed to change acquisition
      parameters such as frequency, gain and modulation.
    """

    config = copy.deepcopy(base_config)

    app_updates = command.get("app", {})
    rf_updates = command.get("rf", {})

    allowed_app_fields = {
        "mode",
        "update_period_s",
    }

    allowed_rf_fields = {
        "center_frequency_hz",
        "sample_rate_hz",
        "samples_per_frame",
        "rx_gain_db",
        "sps",
        "data_bits",
        "tone_frequency_hz",
    }

    for key, value in app_updates.items():
        if key in allowed_app_fields:
            config["app"][key] = value

    for key, value in rf_updates.items():
        if key in allowed_rf_fields:
            config["rf"][key] = value

    _validate_runtime_config(config)

    return config


# ---------------------------------------------------------------------
# Metric message
# ---------------------------------------------------------------------

def _result_to_message(
    *,
    config: dict[str, Any],
    result,
    group: str,
    metadata_by_uri: dict[str, dict[str, Any]],
    sequence: int,
) -> dict[str, Any]:

    power_map = result.group_powers[group]
    snr_map = result.group_snrs[group]

    radios: list[dict[str, Any]] = []

    for uri, power_db in power_map.items():
        meta = metadata_by_uri.get(
            uri,
            {
                "label": uri,
                "serial": None,
                "uri": uri,
            },
        )

        radios.append(
            {
                "label": meta["label"],
                "serial": meta.get("serial"),
                "uri": uri,
                "power_db": _finite_or_none(
                    power_db
                ),
                "snr_db": _finite_or_none(
                    snr_map.get(uri)
                ),
            }
        )

    # Determine strongest and weakest locally.
    # The central server will calculate them again after
    # combining all received information.
    valid_radios = [
        radio
        for radio in radios
        if radio["power_db"] is not None
    ]

    strongest = None
    weakest = None

    if valid_radios:
        strongest = max(
            valid_radios,
            key=lambda r: r["power_db"],
        )

        weakest = min(
            valid_radios,
            key=lambda r: r["power_db"],
        )

    return {
        "type": "rx_metrics",

        "node_id": str(config["node"]["id"]),
        "role": "receiver",
        "group": group,

        "sequence": sequence,
        "timestamp": result.timestamp,

        "mode": str(
            config["app"]["mode"]
        ),

        "radios": radios,

        "summary": {
            "strongest_label": (
                strongest["label"]
                if strongest
                else None
            ),
            "strongest_db": (
                strongest["power_db"]
                if strongest
                else None
            ),

            "weakest_label": (
                weakest["label"]
                if weakest
                else None
            ),
            "weakest_db": (
                weakest["power_db"]
                if weakest
                else None
            ),

            "mean_power_db": _finite_or_none(
                result.group_mean_power_db.get(
                    group
                )
            ),

            "mean_noise_db": _finite_or_none(
                result.group_mean_noise_db.get(
                    group
                )
            ),
        },
    }


# ---------------------------------------------------------------------
# Status messages
# ---------------------------------------------------------------------

def _build_status_message(
    *,
    config: dict[str, Any],
    state: str,
    connected_radios: int,
) -> dict[str, Any]:

    return {
        "type": "rx_status",

        "node_id": str(
            config["node"]["id"]
        ),

        "role": "receiver",

        "group": str(
            config["node"]["group"]
        ),

        "state": state,

        "connected_radios": connected_radios,

        "timestamp": time.time(),
    }


def _build_error_message(
    config: dict[str, Any],
    error: str,
) -> dict[str, Any]:

    return {
        "type": "rx_error",

        "node_id": str(
            config["node"]["id"]
        ),

        "role": "receiver",

        "group": str(
            config["node"]["group"]
        ),

        "timestamp": time.time(),

        "error": str(error),
    }


# ---------------------------------------------------------------------
# Control response
# ---------------------------------------------------------------------

def _send_control_response(
    sock: socket.socket,
    addr: tuple[str, int],
    *,
    command: str,
    node_id: str,
    success: bool,
    state: str,
    error: str | None = None,
) -> None:

    response = {
        "type": "rx_command_response",
        "command": command,
        "node_id": node_id,
        "success": success,
        "state": state,
        "timestamp": time.time(),
    }

    if error is not None:
        response["error"] = error

    sock.sendto(
        dumps_message(response),
        addr,
    )


# ---------------------------------------------------------------------
# Main RX node
# ---------------------------------------------------------------------

def run(config_path: str) -> None:

    base_config = load_config(config_path)

    node_cfg = base_config["node"]
    net_cfg = base_config["network"]

    node_id = str(node_cfg["id"])
    group = str(node_cfg["group"])

    # -------------------------------------------------------------
    # Metrics connection
    # -------------------------------------------------------------

    central_host = str(
        net_cfg["central_host"]
    )

    metrics_port = int(
        net_cfg.get(
            "metrics_port",
            net_cfg.get(
                "central_port",
                5555,
            ),
        )
    )

    metrics_client = UdpJsonClient(
        host=central_host,
        port=metrics_port,
    )

    # -------------------------------------------------------------
    # Control socket
    # -------------------------------------------------------------

    control_host = str(
        net_cfg.get(
            "control_host",
            "0.0.0.0",
        )
    )

    control_port = int(
        net_cfg.get(
            "control_port",
            5556,
        )
    )

    control_sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
    )

    control_sock.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1,
    )

    control_sock.bind(
        (
            control_host,
            control_port,
        )
    )

    control_sock.setblocking(False)

    # -------------------------------------------------------------
    # Runtime state
    # -------------------------------------------------------------

    receivers: dict[str, PlutoReceiver] = {}

    metadata_by_uri: dict[
        str,
        dict[str, Any],
    ] = {}

    active_config = copy.deepcopy(
        base_config
    )

    running = False

    sequence = 0

    next_acquisition = 0.0

    heartbeat_period_s = float(
        net_cfg.get(
            "heartbeat_period_s",
            2.0,
        )
    )

    next_heartbeat = 0.0

    consecutive_errors = 0

    # -------------------------------------------------------------
    # Startup
    # -------------------------------------------------------------

    print()
    print("=" * 60)
    print("Pluto Monitor RX node")
    print("=" * 60)

    print(f"Node ID:       {node_id}")
    print(f"Group:         {group}")

    print(
        f"Metrics:       "
        f"{central_host}:{metrics_port}"
    )

    print(
        f"Control:       "
        f"{control_host}:{control_port}"
    )

    print()
    print(
        "State: IDLE - waiting for START command"
    )
    print()

    try:

        while True:

            now = time.monotonic()

            # -----------------------------------------------------
            # Determine how long select() may wait
            # -----------------------------------------------------

            timeout = 0.25

            if running:
                timeout = max(
                    0.0,
                    min(
                        0.25,
                        next_acquisition - now,
                    ),
                )

            readable, _, _ = select.select(
                [control_sock],
                [],
                [],
                timeout,
            )

            # -----------------------------------------------------
            # Process control messages
            # -----------------------------------------------------

            if readable:

                while True:

                    try:
                        raw_data, addr = (
                            control_sock.recvfrom(
                                65535
                            )
                        )

                    except BlockingIOError:
                        break

                    try:
                        command_msg = (
                            loads_message(
                                raw_data
                            )
                        )

                    except Exception as exc:
                        print(
                            f"Invalid command "
                            f"from {addr}: {exc}"
                        )
                        continue

                    if (
                        command_msg.get("type")
                        != "rx_command"
                    ):
                        continue

                    command = str(
                        command_msg.get(
                            "command",
                            "",
                        )
                    ).lower()

                    # -------------------------------------------------
                    # START
                    # -------------------------------------------------

                    if command == "start":

                        print()
                        print(
                            f"START received from "
                            f"{addr[0]}"
                        )

                        try:

                            # Stop any previous acquisition
                            running = False

                            _close_receivers(
                                receivers
                            )

                            metadata_by_uri = {}

                            # Apply configuration sent by server
                            active_config = (
                                _build_runtime_config(
                                    base_config,
                                    command_msg,
                                )
                            )

                            # Connect physical radios
                            (
                                receivers,
                                metadata_by_uri,
                            ) = _build_receivers(
                                active_config
                            )

                            running = True
                            sequence = 0
                            consecutive_errors = 0

                            next_acquisition = (
                                time.monotonic()
                            )

                            print()
                            print(
                                "RX acquisition started"
                            )

                            print(
                                f"Mode: "
                                f"{active_config['app']['mode']}"
                            )

                            print(
                                f"Center frequency: "
                                f"{active_config['rf']['center_frequency_hz']} Hz"
                            )

                            print(
                                f"Sample rate: "
                                f"{active_config['rf']['sample_rate_hz']} Hz"
                            )

                            print(
                                f"RX gain: "
                                f"{active_config['rf']['rx_gain_db']} dB"
                            )

                            _send_control_response(
                                control_sock,
                                addr,
                                command="start",
                                node_id=node_id,
                                success=True,
                                state="running",
                            )

                        except Exception as exc:

                            running = False

                            _close_receivers(
                                receivers
                            )

                            error_text = str(exc)

                            print(
                                f"START failed: "
                                f"{error_text}"
                            )

                            _send_control_response(
                                control_sock,
                                addr,
                                command="start",
                                node_id=node_id,
                                success=False,
                                state="error",
                                error=error_text,
                            )

                            metrics_client.send(
                                _build_error_message(
                                    base_config,
                                    error_text,
                                )
                            )

                    # -------------------------------------------------
                    # STOP
                    # -------------------------------------------------

                    elif command == "stop":

                        print()
                        print(
                            f"STOP received from "
                            f"{addr[0]}"
                        )

                        running = False

                        _close_receivers(
                            receivers
                        )

                        metadata_by_uri = {}

                        print(
                            "RX acquisition stopped"
                        )

                        _send_control_response(
                            control_sock,
                            addr,
                            command="stop",
                            node_id=node_id,
                            success=True,
                            state="idle",
                        )

                    # -------------------------------------------------
                    # PING / STATUS
                    # -------------------------------------------------

                    elif command in {
                        "ping",
                        "status",
                    }:

                        state = (
                            "running"
                            if running
                            else "idle"
                        )

                        _send_control_response(
                            control_sock,
                            addr,
                            command=command,
                            node_id=node_id,
                            success=True,
                            state=state,
                        )

                    else:

                        _send_control_response(
                            control_sock,
                            addr,
                            command=command,
                            node_id=node_id,
                            success=False,
                            state=(
                                "running"
                                if running
                                else "idle"
                            ),
                            error=(
                                "Unknown command"
                            ),
                        )

            # -----------------------------------------------------
            # Heartbeat
            # -----------------------------------------------------

            now = time.monotonic()

            if now >= next_heartbeat:

                state = (
                    "running"
                    if running
                    else "idle"
                )

                metrics_client.send(
                    _build_status_message(
                        config=base_config,
                        state=state,
                        connected_radios=(
                            len(receivers)
                        ),
                    )
                )

                next_heartbeat = (
                    now
                    + heartbeat_period_s
                )

            # -----------------------------------------------------
            # Acquisition
            # -----------------------------------------------------

            if (
                running
                and now >= next_acquisition
            ):

                acquisition_start = (
                    time.monotonic()
                )

                try:

                    acquisition_groups = {
                        group: {
                            "radio_ids": list(
                                receivers.keys()
                            )
                        }
                    }

                    result = acquire_once(
                        groups=acquisition_groups,
                        receivers=receivers,
                        mode=str(
                            active_config["app"][
                                "mode"
                            ]
                        ),
                        rf_config=(
                            active_config["rf"]
                        ),
                    )

                    sequence += 1

                    message = (
                        _result_to_message(
                            config=active_config,
                            result=result,
                            group=group,
                            metadata_by_uri=(
                                metadata_by_uri
                            ),
                            sequence=sequence,
                        )
                    )

                    metrics_client.send(
                        message
                    )

                    consecutive_errors = 0

                    summary = message[
                        "summary"
                    ]

                    strongest = (
                        summary[
                            "strongest_label"
                        ]
                        or "---"
                    )

                    weakest = (
                        summary[
                            "weakest_label"
                        ]
                        or "---"
                    )

                    print(
                        f"\r"
                        f"seq={sequence:<6} "
                        f"group={group} "
                        f"strongest={strongest:<8} "
                        f"weakest={weakest:<8}",
                        end="",
                        flush=True,
                    )

                except Exception as exc:

                    consecutive_errors += 1

                    print()
                    print(
                        f"Acquisition error "
                        f"({consecutive_errors}): "
                        f"{exc}"
                    )

                    metrics_client.send(
                        _build_error_message(
                            base_config,
                            str(exc),
                        )
                    )

                    # Avoid endless failures if a Pluto
                    # disappears physically.
                    if consecutive_errors >= 3:

                        print(
                            "Too many consecutive "
                            "acquisition errors. "
                            "Returning to IDLE."
                        )

                        running = False

                        _close_receivers(
                            receivers
                        )

                        metadata_by_uri = {}

                # ---------------------------------------------
                # Maintain requested update period
                # ---------------------------------------------

                elapsed = (
                    time.monotonic()
                    - acquisition_start
                )

                update_period = float(
                    active_config["app"].get(
                        "update_period_s",
                        0.5,
                    )
                )

                next_acquisition = (
                    time.monotonic()
                    + max(
                        0.0,
                        update_period - elapsed,
                    )
                )

    except KeyboardInterrupt:

        print()
        print(
            "Stopping RX node..."
        )

    finally:

        running = False

        _close_receivers(
            receivers
        )

        control_sock.close()

        metrics_client.close()

        print(
            "RX node stopped."
        )


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Run one Raspberry Pi "
            "Pluto receiver node"
        )
    )

    parser.add_argument(
        "--config",
        required=True,
        help=(
            "Path to RX node YAML "
            "configuration"
        ),
    )

    args = parser.parse_args()

    run(args.config)


if __name__ == "__main__":
    main()