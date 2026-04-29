from __future__ import annotations

import time

from pluto_monitor.config.loader import load_config
from pluto_monitor.hardware.discovery import (
    ResolvedRadioTopology,
    resolve_topology,
    validate_required_radios,
)
from pluto_monitor.hardware.receiver import PlutoReceiver, ReceiverConfig
from pluto_monitor.hardware.transmitter import PlutoTransmitter, TransmitterConfig
from pluto_monitor.models.history import MetricHistory
from pluto_monitor.services.acquisition import acquire_once
from pluto_monitor.utils.plotting import export_group_plots


def build_receivers(
    config: dict,
    resolved: ResolvedRadioTopology,
) -> tuple[dict[str, PlutoReceiver], dict[str, list[str]]]:
    rf = config["rf"]
    groups_cfg = config["clusters"]["groups"]

    receivers: dict[str, PlutoReceiver] = {}
    resolved_groups: dict[str, list[str]] = {}

    for group_name, group_data in groups_cfg.items():
        serials = [serial.lower() for serial in group_data["radio_serials"]]
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


def build_transmitter(
    config: dict,
    resolved: ResolvedRadioTopology,
) -> PlutoTransmitter:
    rf = config["rf"]

    tx_cfg = TransmitterConfig(
        radio_id=resolved.transmitter_uri,
        center_frequency_hz=rf["center_frequency_hz"],
        sample_rate_hz=rf["sample_rate_hz"],
        tx_gain_db=rf["tx_gain_db"],
    )

    transmitter = PlutoTransmitter(tx_cfg)
    transmitter.connect()
    return transmitter


def build_tx_waveform(
    transmitter: PlutoTransmitter,
    config: dict,
) -> tuple[str, object]:
    app_cfg = config["app"]
    rf = config["rf"]
    mode = app_cfg["mode"]

    if mode == "SineWave":
        tx_waveform = transmitter.build_tone(
            tone_frequency_hz=rf["tone_frequency_hz"],
            num_samples=rf["samples_per_frame"],
        )
        transmitter.transmit_repeat(tx_waveform)
        return mode, None

    if mode == "BPSK":
        tx_waveform, tx_bits, tx_symbols = transmitter.build_bpsk(
            data_bits=rf["data_bits"],
            sps=rf["sps"],
        )
        transmitter.transmit_repeat(tx_waveform)
        return mode, {
            "tx_bits": tx_bits,
            "tx_symbols": tx_symbols,
        }
    
    if mode == "QPSK":
        tx_waveform, tx_bits, tx_symbols = transmitter.build_qpsk(
            data_bits=rf["data_bits"],
            sps=rf["sps"],
        )
        transmitter.transmit_repeat(tx_waveform)
        return mode, {
            "tx_bits": tx_bits,
            "tx_symbols": tx_symbols,
        }   
    

    raise NotImplementedError(f"Mode {mode} is not implemented yet in Python")


def print_result(result) -> None:
    print(f"\nTimestamp: {result.timestamp:.3f}")

    for group_name, power_map in result.group_powers.items():
        snr_map = result.group_snrs[group_name]

        print(f"Group {group_name}:")
        for radio_uri, power_db in power_map.items():
            snr_db = snr_map.get(radio_uri, float("nan"))
            print(f"  {radio_uri}: {power_db:.2f} dB | SNR: {snr_db:.2f} dB")

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

    app_cfg = config["app"]

    receivers: dict[str, PlutoReceiver] = {}
    resolved_groups: dict[str, list[str]] = {}
    transmitter: PlutoTransmitter | None = None

    history = MetricHistory(
        max_points=int(config["runtime"].get("max_history_points", 100))
    )

    resolved = resolve_topology(config)

    try:
        print("Resolved topology:")
        for serial, uri in resolved.serial_to_uri.items():
            print(f"  {serial} -> {uri}")

        print("Connecting receivers...")
        receivers, resolved_groups = build_receivers(config, resolved)
        print(f"Connected RX radios: {list(receivers.keys())}")

        print("Connecting transmitter...")
        transmitter = build_transmitter(config, resolved)
        print(f"Connected TX radio: {transmitter.config.radio_id}")

        print(f"Starting transmission for mode: {app_cfg['mode']}")
        mode, tx_debug = build_tx_waveform(transmitter, config)

        if mode in ("BPSK", "QPSK") and tx_debug is not None:
            tx_bits = tx_debug["tx_bits"]
            tx_symbols = tx_debug["tx_symbols"]
            print(
                f"BPSK TX ready: payload_bits={len(tx_bits)}, "
                f"total_symbols={len(tx_symbols)}"
            )

        update_period_s = float(app_cfg["update_period_s"])
        print("Starting acquisition loop. Press Ctrl+C to stop.")

        acquisition_groups = {
            group_name: {"radio_ids": uris}
            for group_name, uris in resolved_groups.items()
        }

        while True:
            result = acquire_once(
                groups=acquisition_groups,
                receivers=receivers,
                mode=mode,
                rf_config=config["rf"],
            )
            history.append(result.timestamp, result.group_summaries)
            print_result(result)
            time.sleep(update_period_s)

    except KeyboardInterrupt:
        print("\nStopping acquisition...")
    finally:
        for receiver in receivers.values():
            receiver.close()

        if transmitter is not None:
            transmitter.close()

        export_dir = config["runtime"]["export_dir"]
        weak_path, strong_path = export_group_plots(history, export_dir)
        print(f"Saved weakest plot to: {weak_path}")
        print(f"Saved strongest plot to: {strong_path}")