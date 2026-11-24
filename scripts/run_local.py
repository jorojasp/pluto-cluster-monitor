"""Console and Matplotlib monitor for radios attached to this PC.

Usage: python scripts/run_local.py [--config configs/default.yaml]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pluto_monitor.app import run_continuous

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the local Pluto monitor")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config")
    args = parser.parse_args()
    if not Path(args.config).is_file():
        parser.error(
            f"{args.config} not found from {Path.cwd()}. Run from the repository root, or "
            "create it with: cp configs/default.yaml configs/local.yaml"
        )
    run_continuous(args.config)
