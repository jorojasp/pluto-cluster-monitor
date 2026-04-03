from dataclasses import dataclass


@dataclass
class GroupSummary:
    strongest_label: str
    strongest_db: float
    weakest_label: str
    weakest_db: float


def summarize_group(power_map: dict[str, float]) -> GroupSummary:
    valid_items = [(k, v) for k, v in power_map.items() if v == v]
    if not valid_items:
        return GroupSummary("---", float("nan"), "---", float("nan"))

    strongest = max(valid_items, key=lambda item: item[1])
    weakest = min(valid_items, key=lambda item: item[1])

    return GroupSummary(
        strongest_label=strongest[0],
        strongest_db=strongest[1],
        weakest_label=weakest[0],
        weakest_db=weakest[1],
    )