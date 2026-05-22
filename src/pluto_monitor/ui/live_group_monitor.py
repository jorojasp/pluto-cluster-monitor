from __future__ import annotations

from collections import defaultdict, deque

import matplotlib.pyplot as plt


class LiveGroupMonitor:
    def __init__(self, max_points: int = 100) -> None:
        self.max_points = max_points
        self.timestamps = deque(maxlen=max_points)
        self.power_history = defaultdict(lambda: deque(maxlen=max_points))
        self.noise_history = defaultdict(lambda: deque(maxlen=max_points))
        self.power_lines = {}
        self.noise_lines = {}

        plt.ion()
        self.fig, (self.ax_power, self.ax_noise) = plt.subplots(2, 1, figsize=(10, 6))

        self.ax_power.set_title("Group Power")
        self.ax_power.set_xlabel("Sample")
        self.ax_power.set_ylabel("Power [dB]")
        self.ax_power.grid(True)

        self.ax_noise.set_title("Group Noise")
        self.ax_noise.set_xlabel("Sample")
        self.ax_noise.set_ylabel("Noise [dB]")
        self.ax_noise.grid(True)

        self.fig.tight_layout()

    def update(self, result) -> None:
        self.timestamps.append(result.timestamp)

        for group_name, value in result.group_mean_power_db.items():
            self.power_history[group_name].append(value)

        for group_name, value in result.group_mean_noise_db.items():
            self.noise_history[group_name].append(value)

        self._refresh()

    def _refresh(self) -> None:
        for group_name, values in self.power_history.items():
            x = list(range(1, len(values) + 1))
            if group_name not in self.power_lines:
                line, = self.ax_power.plot([], [], label=group_name)
                self.power_lines[group_name] = line
                self.ax_power.legend()
            self.power_lines[group_name].set_data(x, list(values))

        for group_name, values in self.noise_history.items():
            x = list(range(1, len(values) + 1))
            if group_name not in self.noise_lines:
                line, = self.ax_noise.plot([], [], label=group_name)
                self.noise_lines[group_name] = line
                self.ax_noise.legend()
            self.noise_lines[group_name].set_data(x, list(values))

        self.ax_power.relim()
        self.ax_power.autoscale_view()

        self.ax_noise.relim()
        self.ax_noise.autoscale_view()

        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        plt.pause(0.001)

    def close(self) -> None:
        plt.ioff()
        plt.close(self.fig)