"""Console and Matplotlib monitor for radios attached to this PC.

Usage: python scripts/run_local.py [--config configs/default.yaml]
"""
from __future__ import annotations

import argparse

from pluto_monitor.app import run_continuous

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the local Pluto monitor")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config")
    run_continuous(parser.parse_args().config)
