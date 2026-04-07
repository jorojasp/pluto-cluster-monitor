from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MetricHistory:
    timestamps: list[float] = field(default_factory=list)
    weakest_by_group: dict[str, list[float]] = field(default_factory=dict)
    strongest_by_group: dict[str, list[float]] = field(default_factory=dict)
    max_points: int = 100

    def append(
        self,
        timestamp: float,
        group_summaries: dict,
    ) -> None:
        self.timestamps.append(timestamp)

        for group_name, summary in group_summaries.items():
            self.weakest_by_group.setdefault(group_name, []).append(summary.weakest_db)
            self.strongest_by_group.setdefault(group_name, []).append(summary.strongest_db)

        self._trim()

    def _trim(self) -> None:
        if len(self.timestamps) > self.max_points:
            self.timestamps = self.timestamps[-self.max_points:]

        for data in self.weakest_by_group.values():
            if len(data) > self.max_points:
                del data[:-self.max_points]

        for data in self.strongest_by_group.values():
            if len(data) > self.max_points:
                del data[:-self.max_points]