from __future__ import annotations

import math
import time

from pluto_monitor.config.loader import load_config
from pluto_monitor.config.runtime import validate
from pluto_monitor.hardware.discovery import resolve_topology, validate_required_radios
from pluto_monitor.hardware.factory import close_receivers
from pluto_monitor.hardware.receiver import PlutoReceiver
from pluto_monitor.hardware.transmitter import PlutoTransmitter
from pluto_monitor.models.history import MetricHistory
from pluto_monitor.services.acquisition import AcquisitionResult, acquire_once
from pluto_monitor.services.iq_recorder import recorder_from_config
from pluto_monitor.services.local_radios import build_receivers, build_transmitter
from pluto_monitor.ui.live_group_monitor import LiveGroupMonitor
from pluto_monitor.utils.plotting import export_group_plots


def print_result(result: AcquisitionResult) -> None:
    print(f"\nTimestamp: {result.timestamp:.3f}")

    for group_name, radios in result.group_metrics.items():
        print(f"Group {group_name}:")
        for radio_uri, metrics in radios.items():
            line = f"  {radio_uri}: {metrics['power_db']:.2f} dB | SNR: {metrics['snr_db']:.2f} dB"
            if not math.isnan(metrics.get("ber", float("nan"))):
                line += f" | BER: {metrics['ber']:.2e} | CFO: {metrics['cfo_hz']:.0f} Hz"
            if not math.isnan(metrics.get("frame_ok", float("nan"))):
                line += (
                    f" | BER after FEC: {metrics['ber_coded']:.2e}"
                    f" | CRC {'ok' if metrics['frame_ok'] else 'FAIL'}"
                    f" | {metrics['throughput_bps'] / 1e6:.2f} Mb/s"
                )
            print(line)

        summary = result.group_summaries[group_name]
        print(f"  mean group power={result.group_mean_power_db[group_name]:.2f} dB")
        print(f"  mean group noise={result.group_mean_noise_db[group_name]:.2f} dB")
        print(f"  strongest={summary.strongest_label} ({summary.strongest_db:.2f} dB)")
        print(f"  weakest={summary.weakest_label} ({summary.weakest_db:.2f} dB)")

    print(f"Stronger group overall: {result.strongest_group}")


def run_continuous(config_path: str = "configs/default.yaml") -> None:
    config = load_config(config_path)
    validate(config)
    validate_required_radios(config)
    resolved = resolve_topology(config)

    mode = str(config["app"]["mode"])
    update_period_s = float(config["app"]["update_period_s"])
    max_points = int(config["runtime"].get("max_history_points", 100))
    history = MetricHistory(max_points=max_points)
    receivers: dict[str, PlutoReceiver] = {}
    transmitter: PlutoTransmitter | None = None
    live_monitor: LiveGroupMonitor | None = None

    try:
        print("Resolved topology:")
        for serial, uri in resolved.serial_to_uri.items():
            print(f"  {serial} -> {uri}")

        receivers, groups = build_receivers(config, resolved)
        print(f"Connected RX radios: {list(receivers)}")

        transmitter = build_transmitter(config, resolved)
        print(f"Transmitting {mode}" if transmitter else "Transmitter disabled")

        recorder = recorder_from_config(config)
        if recorder is not None:
            print(f"Saving IQ to {recorder.path}")

        live_monitor = LiveGroupMonitor(max_points=max_points)
        acquisition_groups = {name: {"radio_ids": uris} for name, uris in groups.items()}
        print("Starting acquisition loop. Press Ctrl+C to stop.")

        while True:
            result = acquire_once(
                groups=acquisition_groups,
                receivers=receivers,
                mode=mode,
                rf_config=config["rf"],
                iq_sink=recorder,
            )
            history.append(result.timestamp, result.group_summaries)
            print_result(result)
            live_monitor.update(result)
            time.sleep(update_period_s)

    except KeyboardInterrupt:
        print("\nStopping acquisition...")
    finally:
        # Stop radiating first, whatever else fails while closing.
        if transmitter is not None:
            transmitter.close()
        close_receivers(receivers)
        if live_monitor is not None:
            live_monitor.close()

    if history.timestamps:
        weak_path, strong_path = export_group_plots(history, config["runtime"]["export_dir"])
        print(f"Saved weakest plot to: {weak_path}")
        print(f"Saved strongest plot to: {strong_path}")
