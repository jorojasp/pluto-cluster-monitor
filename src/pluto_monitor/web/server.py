from __future__ import annotations

import copy
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
import anyio.to_thread
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pluto_monitor.config.loader import load_config
from pluto_monitor.config.runtime import apply_overrides, split_overrides
from pluto_monitor.dsp.modes import MODES
from pluto_monitor.nodes.central_server import DistributedRxCoordinator
from pluto_monitor.nodes.tx_node import LocalTxController
from pluto_monitor.web.schemas import StartRequest
from pluto_monitor.web.service import AcquisitionService

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
        # self.lock guards short state reads and writes. self._operation
        # serializes Start and Stop, which wait for the network.
        self.lock = threading.RLock()
        self._operation = threading.Lock()
        self.state = "idle"
        self.error: str | None = None

    def open(self) -> None:
        self.coordinator.start()

    def close(self) -> None:
        for name, action in (
            ("TX", self.tx.stop),
            ("RX", lambda: self.coordinator.stop_receivers(timeout=2.0)),
        ):
            try:
                action()
            except Exception as exc:
                print(f"Could not stop {name} while closing: {exc}")
        self.coordinator.close()

    def load_config(self) -> dict[str, Any]:
        return {
            "app": copy.deepcopy(self.base_config["app"]),
            "rf": copy.deepcopy(self.base_config["rf"]),
        }

    def start(self, overrides: dict[str, Any]) -> None:
        app, rf = split_overrides(overrides)
        config = apply_overrides(self.base_config, app, rf)

        with self.lock:
            if self.state in {"starting", "running", "stopping"}:
                raise RuntimeError(f"Cannot start while state is {self.state}")
            self.state = "starting"
            self.error = None

        with self._operation:
            try:
                self._start(config)
            except Exception as exc:
                self.coordinator.end_session("start_failed")
                with self.lock:
                    self.state = "error"
                    self.error = str(exc)
                raise
            with self.lock:
                self.active_config = config
                self.state = "running"

    def _start(self, config: dict[str, Any]) -> None:
        timeout = float(config.get("runtime", {}).get("command_timeout_s", 30.0))
        self.coordinator.start_session(config["app"], config["rf"])
        try:
            responses = self.coordinator.start_receivers(
                app=config["app"], rf=config["rf"], timeout=timeout
            )
            failed = [
                f"{node}: {response.get('error', 'start failed')}"
                for node, response in responses.items()
                if not response.get("success")
            ]
            if failed:
                raise RuntimeError(f"RX start failed: {'; '.join(failed)}")

            if config["app"].get("transmit_enabled", True):
                self.tx.start(app=config["app"], rf=config["rf"])
            else:
                self.tx.stop()
        except Exception:
            try:
                self.coordinator.stop_receivers(timeout=3.0)
            except Exception as exc:
                print(f"Could not stop receivers after a failed start: {exc}")
            raise

    def stop(self) -> None:
        with self._operation:
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
                        self.base_config.get("runtime", {}).get("command_timeout_s", 10.0)
                    )
                )
                errors += [
                    f"{node}: {response.get('error', 'stop failed')}"
                    for node, response in responses.items()
                    if not response.get("success")
                ]
            except Exception as exc:
                errors.append(f"RX: {exc}")

            self.coordinator.end_session("stop_failed" if errors else "stopped")
            with self.lock:
                self.state = "error" if errors else "idle"
                self.error = "; ".join(errors) or None
            if errors:
                raise RuntimeError("; ".join(errors))

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
                "session_id": self.coordinator.session_id,
                "session_log": self.coordinator.session_log_path,
            }

    def metrics(self) -> dict[str, Any] | None:
        metrics = self.coordinator.get_metrics()
        if not metrics.get("groups"):
            return None
        return metrics


def create_service(config_path: str) -> DistributedService | AcquisitionService:
    """Choose the provider from the configuration.

    `clusters` describes radios attached to this PC and `network` describes
    remote receiver nodes.
    """
    config = load_config(config_path)
    if "clusters" in config:
        return AcquisitionService(config_path)
    if "network" in config:
        return DistributedService(config_path)
    raise ValueError(f"{config_path} needs a 'clusters' (local) or 'network' (distributed) section")


service: DistributedService | AcquisitionService | None = None


def get_service() -> DistributedService | AcquisitionService:
    if service is None:
        raise RuntimeError("Service not initialized")
    return service


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service
    service = create_service(CONFIG_PATH)
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
    modes = [{"name": m.name, "controls": m.controls} for m in MODES.values()]
    return {**get_service().load_config(), "modes": modes}


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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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

            # Collected in a thread: a slow lock must not stop the event loop.
            payload = await anyio.to_thread.run_sync(
                lambda srv=srv: {"status": srv.status(), "metrics": srv.metrics()}
            )
            await websocket.send_json(payload)

            await anyio.sleep(WS_PUSH_INTERVAL_S)

    except WebSocketDisconnect:
        pass
