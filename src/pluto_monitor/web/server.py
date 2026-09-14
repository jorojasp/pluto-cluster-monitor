from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pluto_monitor.web.schemas import StartRequest, StatusResponse
from pluto_monitor.web.service import AcquisitionService, ServiceStateError

STATIC_DIR = Path(__file__).parent / "static"

# Polling interval for the WebSocket push loop. This is independent from
# the hardware acquisition period (`app.update_period_s` in the YAML
# config) -- it just controls how often the browser is refreshed with
# whatever the latest snapshot happens to be.
WS_PUSH_INTERVAL_S = 0.2

CONFIG_PATH = os.environ.get("PLUTO_MONITOR_CONFIG", "configs/default.yaml")

app = FastAPI(title="Pluto Cluster Monitor")
service = AcquisitionService(config_path=CONFIG_PATH)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _status_response() -> StatusResponse:
    status = service.get_status()
    return StatusResponse(
        state=status.state,
        mode=status.mode,
        error=status.error,
        connected_radios=status.connected_radios,
        groups=status.groups,
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    try:
        return service.load_base_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/status", response_model=StatusResponse)
def get_status() -> StatusResponse:
    return _status_response()


@app.get("/api/metrics")
def get_metrics() -> dict[str, Any] | None:
    return service.get_snapshot()


@app.post("/api/start", response_model=StatusResponse)
def start(request: StartRequest) -> StatusResponse:
    try:
        service.start(request.model_dump(exclude_none=True))
    except ServiceStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _status_response()


@app.post("/api/stop", response_model=StatusResponse)
def stop() -> StatusResponse:
    try:
        service.stop()
    except ServiceStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _status_response()


@app.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket) -> None:
    import anyio

    await websocket.accept()
    try:
        while True:
            payload = {
                "status": _status_response().model_dump(),
                "metrics": service.get_snapshot(),
            }
            await websocket.send_json(payload)
            await anyio.sleep(WS_PUSH_INTERVAL_S)
    except WebSocketDisconnect:
        pass
