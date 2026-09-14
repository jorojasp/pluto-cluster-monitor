"""Run the local web frontend (Pluto radios connected directly to this PC).

This does NOT touch the Raspberry Pi distributed nodes (`pluto_monitor.nodes`,
`pluto_monitor.network`); it drives receivers/transmitter attached to this
machine, the same hardware path as `scripts/run_local.py`, but exposes them
through a browser dashboard (FastAPI + WebSocket) instead of a blocking
console loop.

Usage:
    python scripts/run_web.py
    python scripts/run_web.py --config configs/default.yaml --port 8000

Requires the extra "web" dependencies:
    pip install -r requirements-web.txt
"""
from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Pluto Cluster Monitor web frontend (local PC radios)"
    )
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload", action="store_true", help="Enable uvicorn autoreload (development only)"
    )
    args = parser.parse_args()

    os.environ["PLUTO_MONITOR_CONFIG"] = args.config

    import uvicorn

    uvicorn.run(
        "pluto_monitor.web.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
