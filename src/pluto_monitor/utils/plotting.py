from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from pluto_monitor.models.history import MetricHistory


def export_group_plots(
    history: MetricHistory,
    export_dir: str | Path,
) -> tuple[Path, Path]:
    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)

    weak_path = export_path / "weakest_signal.png"
    strong_path = export_path / "strongest_signal.png"

    # Weakest
    plt.figure(figsize=(10, 5))
    for group_name, values in history.weakest_by_group.items():
        x = list(range(1, len(values) + 1))
        plt.plot(x, values, label=f"{group_name} weakest")
    plt.title("Weakest Signal by Group")
    plt.xlabel("Sample")
    plt.ylabel("Signal strength [dB]")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(weak_path)
    plt.close()

    # Strongest
    plt.figure(figsize=(10, 5))
    for group_name, values in history.strongest_by_group.items():
        x = list(range(1, len(values) + 1))
        plt.plot(x, values, label=f"{group_name} strongest")
    plt.title("Strongest Signal by Group")
    plt.xlabel("Sample")
    plt.ylabel("Signal strength [dB]")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(strong_path)
    plt.close()

    return weak_path, strong_path