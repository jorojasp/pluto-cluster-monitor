from __future__ import annotations

import argparse
import time
from typing import Any

from pluto_monitor.config.loader import load_config
from pluto_monitor.hardware.discovery import resolve_uri_from_serial
from pluto_monitor.hardware.receiver import PlutoReceiver, ReceiverConfig
from pluto_monitor.network.udp_client import UdpJsonClient
from pluto_monitor.services.acquisition import acquire_once


def _resolve_radio_uri(radio_cfg: dict[str, Any]) -> tuple[str, str | None]:
    """Return (uri, serial). Allows either explicit uri or serial in YAML."""
    if "uri" in radio_cfg and radio_cfg["uri"]:
        return str(radio_cfg["uri"]), radio_cfg.get("serial")
    if "serial" not in radio_cfg or not radio_cfg["serial"]:
        raise ValueError("Each RX radio needs either 'uri' or 'serial'")
    serial = str(radio_cfg["serial"]).lower()
    return resolve_uri_from_serial(serial), serial


def _build_receivers(config: dict[str, Any]) -> tuple[dict[str, PlutoReceiver], dict[str, dict[str, Any]]]:
    rf = config["rf"]
    receivers: dict[str, PlutoReceiver] = {}
    metadata_by_uri: dict[str, dict[str, Any]] = {}

    for idx, radio_cfg in enumerate(config.get("radios", []), start=1):
        uri, serial = _resolve_radio_uri(radio_cfg)
        label = str(radio_cfg.get("label") or f"rx{idx}")

        rx_cfg = ReceiverConfig(
            radio_id=uri,
            center_frequency_hz=int(rf["center_frequency_hz"]),
            sample_rate_hz=int(rf["sample_rate_hz"]),
            samples_per_frame=int(rf["samples_per_frame"]),
            rx_gain_db=float(rf["rx_gain_db"]),
        )
        receiver = PlutoReceiver(rx_cfg)
        receiver.connect()

        receivers[uri] = receiver
        metadata_by_uri[uri] = {
            "label": label,
            "serial": serial,
            "uri": uri,
        }

    if not receivers:
        raise ValueError("No RX radios configured under 'radios:'")

    return receivers, metadata_by_uri


def _result_to_message(
    *,
    config: dict[str, Any],
    result,
    group: str,
    metadata_by_uri: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    power_map = result.group_powers[group]
    snr_map = result.group_snrs[group]
    summary = result.group_summaries[group]

    radios = []
    for uri, power_db in power_map.items():
        meta = metadata_by_uri.get(uri, {"label": uri, "serial": None, "uri": uri})
        radios.append(
            {
                "label": meta["label"],
                "serial": meta.get("serial"),
                "uri": uri,
                "power_db": power_db,
                "snr_db": snr_map.get(uri, float("nan")),
            }
        )

    return {
        "type": "rx_metrics",
        "node_id": config["node"]["id"],
        "role": "receiver",
        "group": group,
        "timestamp": result.timestamp,
        "mode": config["app"]["mode"],
        "radios": radios,
        "summary": {
            "strongest_label": summary.strongest_label,
            "strongest_db": summary.strongest_db,
            "weakest_label": summary.weakest_label,
            "weakest_db": summary.weakest_db,
            "mean_power_db": result.group_mean_power_db.get(group, float("nan")),
            "mean_noise_db": result.group_mean_noise_db.get(group, float("nan")),
        },
    }


def run(config_path: str) -> None:
    config = load_config(config_path)
    node_cfg = config["node"]
    app_cfg = config["app"]
    net_cfg = config["network"]
    group = str(node_cfg["group"])

    client = UdpJsonClient(
        host=str(net_cfg["central_host"]),
        port=int(net_cfg["central_port"]),
    )

    receivers: dict[str, PlutoReceiver] = {}
    try:
        receivers, metadata_by_uri = _build_receivers(config)
        acquisition_groups = {group: {"radio_ids": list(receivers)}}

        print(f"RX node {node_cfg['id']} ready")
        print(f"Group: {group}")
        print(f"Mode: {app_cfg['mode']}")
        for uri, meta in metadata_by_uri.items():
            print(f"  {meta['label']}: {uri} serial={meta.get('serial')}")

        update_period_s = float(app_cfg.get("update_period_s", 0.5))
        while True:
            t0 = time.monotonic()
            result = acquire_once(
                groups=acquisition_groups,
                receivers=receivers,
                mode=str(app_cfg["mode"]),
                rf_config=config["rf"],
            )
            message = _result_to_message(
                config=config,
                result=result,
                group=group,
                metadata_by_uri=metadata_by_uri,
            )
            client.send(message)

            summary = message["summary"]
            print(
                f"sent group={group} mean={summary['mean_power_db']:.2f} dB "
                f"strongest={summary['strongest_label']} "
                f"weakest={summary['weakest_label']}"
            )
            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, update_period_s - elapsed))

    except KeyboardInterrupt:
        print("Stopping RX node...")
    finally:
        for receiver in receivers.values():
            receiver.close()
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Raspberry Pi receiver node")
    parser.add_argument("--config", required=True, help="Path to RX node YAML config")
    args = parser.parse_args()
    run(args.config)


if __name__ == "__main__":
    main()
