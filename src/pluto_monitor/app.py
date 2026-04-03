from pluto_monitor.config.loader import load_config
from pluto_monitor.dsp.power import compute_power_db
from pluto_monitor.hardware.receiver import PlutoReceiver, ReceiverConfig
from pluto_monitor.services.clustering import summarize_group

def validate_required_radios(configured_rx_ids, configured_tx_id, discovered_ids):
    required = set(configured_rx_ids) | {configured_tx_id}
    missing = required - set(discovered_ids)
    if missing:
        raise RuntimeError(
            f"Missing required Pluto radios: {sorted(missing)}"
        )

def run_once(config_path: str = "configs/default.yaml") -> None:
    cfg = load_config(config_path)
    rf = cfg["rf"]
    runtime = cfg["runtime"]
    groups = cfg["clusters"]["groups"]

    receivers: dict[str, PlutoReceiver] = {}

    try:
        for group_name, group_data in groups.items():
            for radio_id in group_data["radio_ids"]:
                label = f"{group_name}:{radio_id}"
                receiver_cfg = ReceiverConfig(
                    radio_id=radio_id,
                    center_frequency_hz=rf["center_frequency_hz"],
                    sample_rate_hz=rf["sample_rate_hz"],
                    samples_per_frame=rf["samples_per_frame"],
                    rx_gain_db=rf["rx_gain_db"],
                )
                receiver = PlutoReceiver(
                    receiver_cfg,
                )
                receiver.connect()
                receivers[label] = receiver

        summaries = {}
        for group_name, group_data in groups.items():
            power_map: dict[str, float] = {}
            for radio_id in group_data["radio_ids"]:
                label = f"{group_name}:{radio_id}"
                iq = receivers[label].read_samples()
                power_map[radio_id] = compute_power_db(iq)
            summaries[group_name] = summarize_group(power_map)

        print("Cluster summaries")
        for group_name, summary in summaries.items():
            print(
                f"Group {group_name} | "
                f"strongest={summary.strongest_label} ({summary.strongest_db:.2f} dB) | "
                f"weakest={summary.weakest_label} ({summary.weakest_db:.2f} dB)"
            )

    finally:
        for receiver in receivers.values():
            receiver.close()