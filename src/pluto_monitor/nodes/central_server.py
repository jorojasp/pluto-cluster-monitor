from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from pluto_monitor.config.loader import load_config
from pluto_monitor.network.udp_server import UdpJsonServer


def _valid_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not math.isnan(float(value))


def _compute_global_summary(nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for msg in nodes.values():
        if msg.get("type") != "rx_metrics":
            continue
        groups.setdefault(str(msg.get("group", "?")), []).append(msg)

    group_summary: dict[str, dict[str, Any]] = {}
    strongest_group = "---"
    strongest_group_mean = float("-inf")

    for group_name, messages in groups.items():
        radios: list[dict[str, Any]] = []
        mean_values: list[float] = []
        for msg in messages:
            radios.extend(msg.get("radios", []))
            mean_power = msg.get("summary", {}).get("mean_power_db")
            if _valid_number(mean_power):
                mean_values.append(float(mean_power))

        valid_radios = [r for r in radios if _valid_number(r.get("power_db"))]
        strongest = max(valid_radios, key=lambda r: float(r["power_db"]), default=None)
        weakest = min(valid_radios, key=lambda r: float(r["power_db"]), default=None)
        mean_power_db = sum(mean_values) / len(mean_values) if mean_values else float("nan")

        group_summary[group_name] = {
            "mean_power_db": mean_power_db,
            "strongest": strongest,
            "weakest": weakest,
            "radio_count": len(radios),
            "node_count": len(messages),
        }

        if _valid_number(mean_power_db) and mean_power_db > strongest_group_mean:
            strongest_group_mean = mean_power_db
            strongest_group = group_name

    return {
        "groups": group_summary,
        "strongest_group": strongest_group,
    }


def _format_radio(radio: dict[str, Any] | None) -> str:
    if not radio:
        return "---"
    power = radio.get("power_db", float("nan"))
    snr = radio.get("snr_db", float("nan"))
    return f"{radio.get('label', radio.get('uri', '?'))} ({power:.2f} dB, SNR {snr:.2f} dB)"


def _print_status(nodes: dict[str, dict[str, Any]]) -> None:
    summary = _compute_global_summary(nodes)
    print("\n" + "=" * 72)
    print(time.strftime("%Y-%m-%d %H:%M:%S"))
    print(f"Connected RX nodes: {len(nodes)}")

    for group_name, data in sorted(summary["groups"].items()):
        mean_power = data["mean_power_db"]
        print(
            f"Group {group_name}: mean={mean_power:.2f} dB | "
            f"nodes={data['node_count']} | radios={data['radio_count']}"
        )
        print(f"  strongest: {_format_radio(data['strongest'])}")
        print(f"  weakest:   {_format_radio(data['weakest'])}")

    print(f"Stronger group overall: {summary['strongest_group']}")


def run(config_path: str) -> None:
    config = load_config(config_path)
    net_cfg = config["network"]
    runtime_cfg = config.get("runtime", {})
    server = UdpJsonServer(
        host=str(net_cfg.get("listen_host", "0.0.0.0")),
        port=int(net_cfg["listen_port"]),
    )

    nodes: dict[str, dict[str, Any]] = {}
    log_fh = None
    try:
        log_dir = runtime_cfg.get("log_dir")
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            log_path = Path(log_dir) / "rx_metrics.jsonl"
            log_fh = log_path.open("a", encoding="utf-8")
            print(f"Logging metrics to {log_path}")

        print(f"Central server listening on {net_cfg.get('listen_host', '0.0.0.0')}:{net_cfg['listen_port']}")
        while True:
            msg, addr = server.recv()
            if msg.get("type") != "rx_metrics":
                print(f"Ignoring message from {addr}: type={msg.get('type')}")
                continue

            node_id = str(msg.get("node_id", addr[0]))
            msg["_source_addr"] = f"{addr[0]}:{addr[1]}"
            nodes[node_id] = msg

            if log_fh is not None:
                log_fh.write(json.dumps(msg, allow_nan=True) + "\n")
                log_fh.flush()

            _print_status(nodes)

    except KeyboardInterrupt:
        print("Stopping central server...")
    finally:
        server.close()
        if log_fh is not None:
            log_fh.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Receive metrics from Raspberry Pi RX nodes")
    parser.add_argument("--config", required=True, help="Path to central YAML config")
    args = parser.parse_args()
    run(args.config)


if __name__ == "__main__":
    main()
