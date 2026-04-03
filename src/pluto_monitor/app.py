from __future__ import annotations

import time

from pluto_monitor.config.loader import load_config
from pluto_monitor.hardware.discovery import resolve_topology, validate_required_radios
from pluto_monitor.hardware.receiver import PlutoReceiver, ReceiverConfig
from pluto_monitor.hardware.transmitter import PlutoTransmitter, TransmitterConfig
from pluto_monitor.services.acquisition import acquire_once


def build_receivers(config: dict) -> tuple[dict[str, PlutoReceiver], dict[str, list[str]]]:
    rf = config["rf"]
    groups_cfg = config["clusters"]["groups"]
    resolved = resolve_topology(config)

    receivers: dict[str, PlutoReceiver] = {}
    resolved_groups: dict[str, list[str]] = {}

    for group_name, group_data in groups_cfg.items():
        serials = group_data["radio_serials"]
        uris: list[str] = []

        for serial in serials:
            uri = resolved.serial_to_uri[serial]

            receiver_cfg = ReceiverConfig(
                radio_id=uri,
                center_frequency_hz=rf["center_frequency_hz"],
                sample_rate_hz=rf["sample_rate_hz"],
                samples_per_frame=rf["samples_per_frame"],
                rx_gain_db=rf["rx_gain_db"],
            )

            receiver = PlutoReceiver(receiver_cfg)
            receiver.connect()

            receivers[uri] = receiver
            uris.append(uri)

        resolved_groups[group_name] = uris

    return receivers, resolved_groups


def build_transmitter(config: dict) -> PlutoTransmitter:
    rf = config["rf"]
    topology = resolve_topology(config)

    tx_cfg = TransmitterConfig(
        radio_id=topology.transmitter_uri,
        center_frequency_hz=rf["center_frequency_hz"],
        sample_rate_hz=rf["sample_rate_hz"],
        tx_gain_db=rf["tx_gain_db"],
    )

    transmitter = PlutoTransmitter(tx_cfg)
    transmitter.connect()
    return transmitter


def print_result(result) -> None:
    print(f"\nTimestamp: {result.timestamp:.3f}")

    for group_name, power_map in result.group_powers.items():
        print(f"Group {group_name}:")
        for radio_uri, power_db in power_map.items():
            print(f"  {radio_uri}: {power_db:.2f} dB")

        summary = result.group_summaries[group_name]
        print(
            f"  strongest={summary.strongest_label} ({summary.strongest_db:.2f} dB)"
        )
        print(
            f"  weakest={summary.weakest_label} ({summary.weakest_db:.2f} dB)"
        )

    print(f"Stronger group overall: {result.strongest_group}")


def run_continuous(config_path: str = "configs/default.yaml") -> None:
    config = load_config(config_path)
    validate_required_radios(config)

    rf = config["rf"]
    app_cfg = config["app"]

    receivers: dict[str, PlutoReceiver] = {}
    resolved_groups: dict[str, list[str]] = {}
    transmitter: PlutoTransmitter | None = None

    try:
        print("Connecting receivers...")
        receivers, resolved_groups = build_receivers(config)
        print(f"Connected RX radios: {list(receivers.keys())}")

        print("Connecting transmitter...")
        transmitter = build_transmitter(config)
        print(f"Connected TX radio: {transmitter.config.radio_id}")

        if app_cfg["mode"] != "SineWave":
            raise NotImplementedError(
                f"Mode {app_cfg['mode']} is not implemented yet in Python"
            )

        print("Starting tone transmission...")
        tone = transmitter.build_tone(
            tone_frequency_hz=rf["tone_frequency_hz"],
            num_samples=rf["samples_per_frame"],
        )
        transmitter.transmit_repeat(tone)

        update_period_s = float(app_cfg["update_period_s"])
        print("Starting acquisition loop. Press Ctrl+C to stop.")

        acquisition_groups = {
            group_name: {"radio_ids": uris}
            for group_name, uris in resolved_groups.items()
        }

        while True:
            result = acquire_once(groups=acquisition_groups, receivers=receivers)
            print_result(result)
            time.sleep(update_period_s)

    except KeyboardInterrupt:
        print("\nStopping acquisition...")
    finally:
        for receiver in receivers.values():
            receiver.close()

        if transmitter is not None:
            transmitter.close()