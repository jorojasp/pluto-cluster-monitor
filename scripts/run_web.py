"""Run the distributed dashboard and local TX controller on the server Pi.

Receiver processes must already be running on rxpi1 and rxpi2.
Usage: python scripts/run_web.py --config configs/rpi_server.yaml --port 8000
"""
from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Pluto Cluster Monitor distributed web server"
    )
    parser.add_argument("--config", default="configs/rpi_server.yaml", help="Path to YAML config")
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
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    main()
