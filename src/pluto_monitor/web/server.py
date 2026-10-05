from __future__ import annotations

import copy
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pluto_monitor.config.loader import load_config
from pluto_monitor.nodes.central_server import DistributedRxCoordinator
from pluto_monitor.nodes.tx_node import LocalTxController
from pluto_monitor.web.schemas import StartRequest

STATIC_DIR = Path(__file__).parent / "static"
CONFIG_PATH = os.environ.get("PLUTO_MONITOR_CONFIG", "configs/rpi_server.yaml")
WS_PUSH_INTERVAL_S = 0.2


class DistributedService:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.base_config = load_config(config_path)
        self.active_config = copy.deepcopy(self.base_config)
        self.coordinator = DistributedRxCoordinator(self.base_config)
        self.tx = LocalTxController(self.base_config)
        self.lock = threading.RLock()
        self.state = "idle"
        self.error: str | None = None

    def open(self) -> None:
        self.coordinator.start()

    def close(self) -> None:
        try:
            self.tx.stop()
        except Exception:
            pass
        try:
            self.coordinator.stop_receivers(timeout=2.0)
        except Exception:
            pass
        self.coordinator.close()

    def load_config(self) -> dict[str, Any]:
        return {
            "app": copy.deepcopy(self.base_config["app"]),
            "rf": copy.deepcopy(self.base_config["rf"]),
        }

    def _make_config(self, overrides: dict[str, Any]) -> dict[str, Any]:
        config = copy.deepcopy(self.base_config)

        app_fields = {"mode", "update_period_s"}
        rf_fields = {
            "center_frequency_hz",
            "sample_rate_hz",
            "rx_gain_db",
            "tx_gain_db",
            "tone_frequency_hz",
            "sps",
            "data_bits",
        }

        for key, value in overrides.items():
            if key in app_fields:
                config["app"][key] = value
            elif key in rf_fields:
                config["rf"][key] = value

        return config

    def start(self, overrides: dict[str, Any]) -> None:
        with self.lock:
            if self.state in {"starting", "running", "stopping"}:
                raise RuntimeError(f"Cannot start while state is {self.state}")

            self.state = "starting"
            self.error = None
            config = self._make_config(overrides)

            with self.coordinator.lock:
                self.coordinator.latest_metrics.clear()

            timeout = float(
                config.get("runtime", {}).get("command_timeout_s", 30.0)
            )

            try:
                responses = self.coordinator.start_receivers(
                    app=config["app"],
                    rf=config["rf"],
                    timeout=timeout,
                )

                failed = {
                    node_id: response
                    for node_id, response in responses.items()
                    if not response.get("success")
                }

                if failed:
                    details = "; ".join(
                        f"{node}: {response.get('error', 'start failed')}"
                        for node, response in failed.items()
                    )
                    try:
                        self.coordinator.stop_receivers(timeout=3.0)
                    except Exception:
                        pass
                    raise RuntimeError(f"RX start failed: {details}")

                try:
                    self.tx.start(
                        app=config["app"],
                        rf=config["rf"],
                    )
                except Exception:
                    try:
                        self.coordinator.stop_receivers(timeout=3.0)
                    except Exception:
                        pass
                    raise

                self.active_config = config
                self.state = "running"

            except Exception as exc:
                self.state = "error"
                self.error = str(exc)
                raise

    def stop(self) -> None:
        with self.lock:
            if self.state == "idle":
                return

            self.state = "stopping"
            errors = []

            try:
                self.tx.stop()
            except Exception as exc:
                errors.append(f"TX: {exc}")

            try:
                responses = self.coordinator.stop_receivers(
                    timeout=float(
                        self.base_config.get("runtime", {}).get(
                            "command_timeout_s", 10.0
                        )
                    )
                )

                for node_id, response in responses.items():
                    if not response.get("success"):
                        errors.append(
                            f"{node_id}: "
                            f"{response.get('error', 'stop failed')}"
                        )
            except Exception as exc:
                errors.append(f"RX: {exc}")

            if errors:
                self.state = "error"
                self.error = "; ".join(errors)
                raise RuntimeError(self.error)

            self.state = "idle"
            self.error = None

    def status(self) -> dict[str, Any]:
        with self.lock:
            nodes = self.coordinator.get_node_status()

            groups: dict[str, list[str]] = {}
            for node_id, node in nodes.items():
                group = str(node.get("group", "?"))
                groups.setdefault(group, []).append(node_id)

            return {
                "state": self.state,
                "mode": self.active_config.get("app", {}).get("mode"),
                "error": self.error,
                "groups": groups,
                "nodes": nodes,
                "tx": self.tx.status(),
            }

    def metrics(self) -> dict[str, Any] | None:
        metrics = self.coordinator.get_metrics()
        if not metrics.get("groups"):
            return None
        return metrics


service: DistributedService | None = None


def get_service() -> DistributedService:
    if service is None:
        raise RuntimeError("Service not initialized")
    return service


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service
    service = DistributedService(CONFIG_PATH)
    service.open()

    try:
        yield
    finally:
        service.close()


app = FastAPI(
    title="Pluto Cluster Monitor",
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return get_service().load_config()


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    return get_service().status()


@app.get("/api/metrics")
def get_metrics() -> dict[str, Any] | None:
    return get_service().metrics()


@app.post("/api/start")
def start(request: StartRequest) -> dict[str, Any]:
    srv = get_service()

    try:
        srv.start(request.model_dump(exclude_none=True))
    except RuntimeError as exc:
        code = 409 if srv.state in {"starting", "running", "stopping"} else 500
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return srv.status()


@app.post("/api/stop")
def stop() -> dict[str, Any]:
    srv = get_service()

    try:
        srv.stop()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return srv.status()


@app.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        while True:
            srv = get_service()

            await websocket.send_json({
                "status": srv.status(),
                "metrics": srv.metrics(),
            })

            await anyio.sleep(WS_PUSH_INTERVAL_S)

    except WebSocketDisconnect:
        pass