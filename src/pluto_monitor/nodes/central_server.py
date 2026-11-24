from __future__ import annotations

import argparse
import copy
import socket
import threading
import time
from typing import Any

from pluto_monitor.config.loader import load_config
from pluto_monitor.network.messages import dumps_message, loads_message
from pluto_monitor.services.session_log import SessionLog


class DistributedRxCoordinator:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.session = SessionLog(config.get("runtime", {}).get("log_dir", "data/logs"))
        net = config["network"]

        self.metrics_host = str(net.get("metrics_host", "0.0.0.0"))
        self.metrics_port = int(net.get("metrics_port", 5555))

        self.nodes = {}
        for node in net.get("receiver_nodes", []):
            node_id = str(node["id"])
            self.nodes[node_id] = {
                "id": node_id,
                "group": str(node["group"]),
                "host": str(node["host"]),
                "control_port": int(node.get("control_port", 5556)),
            }

        if not self.nodes:
            raise ValueError("No receiver nodes configured")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.metrics_host, self.metrics_port))
        self.sock.settimeout(0.5)

        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)

        self.latest_metrics: dict[str, dict[str, Any]] = {}
        self.node_status: dict[str, dict[str, Any]] = {}
        self.node_errors: dict[str, dict[str, Any]] = {}
        self.command_responses: dict[tuple[str, str], dict[str, Any]] = {}

        self.running = False
        self.thread: threading.Thread | None = None

    @property
    def session_id(self) -> str | None:
        return self.session.session_id

    @property
    def session_log_path(self) -> str | None:
        return self.session.path

    def start_session(self, app: dict, rf: dict) -> None:
        with self.lock:
            self.session.start(app, rf)
            self.latest_metrics.clear()

    def end_session(self, reason: str = "stopped") -> None:
        with self.lock:
            self.session.end(reason)

    def start(self) -> None:
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._listen, daemon=True)
        self.thread.start()

        print(
            f"RX coordinator listening on "
            f"{self.metrics_host}:{self.metrics_port}"
        )

    def close(self) -> None:
        self.end_session("closed")
        self.running = False

        self.sock.close()

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)

    def _listen(self) -> None:
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                message = loads_message(data)
                self._handle_message(message, addr)
            except Exception as exc:
                print(f"Invalid UDP message from {addr}: {exc}")

    def _handle_message(
        self,
        message: dict[str, Any],
        addr: tuple[str, int],
    ) -> None:
        message_type = message.get("type")
        node_id = str(message.get("node_id", ""))

        with self.condition:
            if message_type == "rx_metrics":
                self.session.record({**message, "session_id": self.session_id,
                                     "received_at": time.time()})
                group = str(message.get("group", ""))
                if group:
                    self.latest_metrics[group] = copy.deepcopy(message)

                self.node_status[node_id] = {
                    **self.node_status.get(node_id, {}),
                    "state": "running",
                    "group": group,
                    "last_seen": time.time(),
                    "address": addr[0],
                }

            elif message_type == "rx_status":
                self.node_status[node_id] = {
                    "state": message.get("state", "unknown"),
                    "group": message.get("group"),
                    "connected_radios": message.get("connected_radios", 0),
                    "radios": copy.deepcopy(message.get("radios", [])),
                    "last_seen": time.time(),
                    "address": addr[0],
                }

            elif message_type == "rx_error":
                self.node_errors[node_id] = {
                    "error": message.get("error"),
                    "timestamp": message.get("timestamp", time.time()),
                }

                status = self.node_status.setdefault(node_id, {})
                status["state"] = "error"
                status["last_seen"] = time.time()

            elif message_type == "rx_command_response":
                command = str(message.get("command", "")).lower()
                self.command_responses[(node_id, command)] = copy.deepcopy(
                    message
                )
                self.condition.notify_all()

    def _command_all(
        self,
        command: str,
        *,
        app: dict[str, Any] | None = None,
        rf: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, dict[str, Any]]:
        message = {
            "type": "rx_command",
            "command": command,
            "timestamp": time.time(),
        }

        if app is not None:
            message["app"] = app

        if rf is not None:
            message["rf"] = rf

        expected = [(node_id, command) for node_id in self.nodes]
        with self.condition:
            for key in expected:
                self.command_responses.pop(key, None)

        # Name resolution can block for seconds, so send without the lock. A
        # node that cannot be reached must not prevent the others from acting.
        payload = dumps_message(message)
        for node_id, node in self.nodes.items():
            try:
                self.sock.sendto(payload, (node["host"], node["control_port"]))
            except OSError as exc:
                with self.condition:
                    self.command_responses[(node_id, command)] = {
                        "type": "rx_command_response",
                        "command": command,
                        "node_id": node_id,
                        "success": False,
                        "state": "unreachable",
                        "error": f"Cannot reach {node['host']}: {exc}",
                    }

        with self.condition:
            deadline = time.monotonic() + timeout

            while any(key not in self.command_responses for key in expected):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break

                self.condition.wait(timeout=remaining)

            responses = {}

            for node_id, command_name in expected:
                response = self.command_responses.pop(
                    (node_id, command_name),
                    None,
                )

                if response is None:
                    response = {
                        "type": "rx_command_response",
                        "command": command_name,
                        "node_id": node_id,
                        "success": False,
                        "state": "timeout",
                        "error": "Receiver node did not respond",
                    }

                responses[node_id] = response

            return responses

    def start_receivers(
        self,
        app: dict[str, Any],
        rf: dict[str, Any],
        timeout: float = 15.0,
    ) -> dict[str, dict[str, Any]]:
        return self._command_all(
            "start",
            app=app,
            rf=rf,
            timeout=timeout,
        )

    def stop_receivers(
        self,
        timeout: float = 8.0,
    ) -> dict[str, dict[str, Any]]:
        return self._command_all(
            "stop",
            timeout=timeout,
        )

    def get_node_status(self) -> dict[str, Any]:
        with self.lock:
            now = time.time()
            result = {}

            for node_id, node in self.nodes.items():
                status = copy.deepcopy(
                    self.node_status.get(node_id, {})
                )

                last_seen = status.get("last_seen")
                age = (
                    now - last_seen
                    if last_seen is not None
                    else None
                )

                result[node_id] = {
                    "id": node_id,
                    "group": node["group"],
                    "host": node["host"],
                    "state": status.get("state", "offline"),
                    "last_seen": last_seen,
                    "age_s": age,
                    "connected_radios": status.get(
                        "connected_radios", 0
                    ),
                    "radios": status.get("radios", []),
                }

            return result

    def get_metrics(self) -> dict[str, Any]:
        with self.lock:
            groups = {}
            timestamps = []

            for group_name, message in self.latest_metrics.items():
                radios = copy.deepcopy(message.get("radios", []))

                valid = [
                    radio
                    for radio in radios
                    if isinstance(
                        radio.get("power_db"),
                        (int, float),
                    )
                ]

                strongest = (
                    max(valid, key=lambda radio: radio["power_db"])
                    if valid
                    else None
                )

                weakest = (
                    min(valid, key=lambda radio: radio["power_db"])
                    if valid
                    else None
                )

                for radio in radios:
                    radio["is_strongest"] = (
                        strongest is not None
                        and radio.get("label")
                        == strongest.get("label")
                    )
                    radio["is_weakest"] = (
                        weakest is not None
                        and radio.get("label")
                        == weakest.get("label")
                    )

                summary = message.get("summary", {})

                groups[group_name] = {
                    "timestamp": message.get("timestamp"),
                    "sequence": message.get("sequence"),
                    "mode": message.get("mode"),
                    "radios": radios,
                    "mean_power_db": summary.get("mean_power_db"),
                    "mean_noise_db": summary.get("mean_noise_db"),
                    "strongest_radio": (
                        strongest.get("label")
                        if strongest
                        else None
                    ),
                    "strongest_power_db": (
                        strongest.get("power_db")
                        if strongest
                        else None
                    ),
                    "weakest_radio": (
                        weakest.get("label")
                        if weakest
                        else None
                    ),
                    "weakest_power_db": (
                        weakest.get("power_db")
                        if weakest
                        else None
                    ),
                }

                timestamp = message.get("timestamp")
                if isinstance(timestamp, (int, float)):
                    timestamps.append(timestamp)

            strongest_group = None
            valid_groups = [
                (name, data)
                for name, data in groups.items()
                if isinstance(
                    data.get("strongest_power_db"),
                    (int, float),
                )
            ]

            if valid_groups:
                strongest_group = max(
                    valid_groups,
                    key=lambda item: item[1]["strongest_power_db"],
                )[0]

            return {
                "session_id": self.session_id,
                "timestamp": max(timestamps) if timestamps else None,
                "strongest_group": strongest_group,
                "groups": groups,
            }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    coordinator = DistributedRxCoordinator(config)
    coordinator.start()

    print("Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(2)

            status = coordinator.get_node_status()

            for node_id, node in status.items():
                age = node["age_s"]
                age_text = (
                    f"{age:.1f}s"
                    if age is not None
                    else "---"
                )

                print(
                    f"{node_id}: "
                    f"{node['state']} "
                    f"group={node['group']} "
                    f"last={age_text}"
                )

    except KeyboardInterrupt:
        pass
    finally:
        coordinator.close()


if __name__ == "__main__":
    main()
