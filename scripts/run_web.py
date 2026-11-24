"""Run the web dashboard.

Radios attached to this PC:
    python scripts/run_web.py --config configs/default.yaml
Distributed Raspberry Pi nodes (receiver processes must already be running):
    python scripts/run_web.py --config configs/rpi_server.yaml --host 0.0.0.0

There is no login: anyone who can reach the port can start the transmitter.
The default host only accepts connections from this machine.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Pluto Cluster Monitor web dashboard"
    )
    parser.add_argument("--config", default="configs/rpi_server.yaml", help="Path to YAML config")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload", action="store_true", help="Enable uvicorn autoreload (development only)"
    )
    args = parser.parse_args()
    if not Path(args.config).is_file():
        parser.error(
            f"{args.config} not found from {Path.cwd()}. Run from the repository root, or "
            "create it with: cp configs/default.yaml configs/local.yaml"
        )

    os.environ["PLUTO_MONITOR_CONFIG"] = args.config

    import uvicorn

    uvicorn.run(
        "pluto_monitor.web.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    main()
