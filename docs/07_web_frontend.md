# Web Frontend (Local PC Radios)

## Scope

This first frontend iteration targets the **local scenario only**: multiple
ADALM-Pluto radios connected directly to the PC running the process over
USB. It is the web equivalent of `scripts/run_local.py` / `app.py`.

It intentionally does **not** touch:

- `pluto_monitor.nodes` (`rx_node.py`, `tx_node.py`, `central_server.py`),
- `pluto_monitor.network` (`udp_server.py`, `udp_client.py`, `messages.py`).

Those implement the Raspberry Pi distributed architecture and are left
completely untouched.

## Why a web UI instead of a desktop GUI

The distributed architecture already speaks a network protocol: RPi nodes
send `rx_metrics` JSON messages over UDP to `central_server.py`, which
today only prints them. The metrics shape produced there (`radios`,
`group`, `summary`) is effectively the same shape produced locally by
`services.acquisition.acquire_once`.

Building the frontend as a web app (FastAPI + WebSocket) instead of a
native desktop app (PyQt) means that when the distributed architecture is
wired up later, only the *data source* has to change:

- today: `pluto_monitor.web.service.AcquisitionService` drives local
  hardware directly and produces snapshots,
- later: a second provider can read the aggregated state kept by
  `central_server.py` and expose the same JSON shape.

The static frontend (`web/static/`) and the WebSocket contract
(`{"status": ..., "metrics": ...}`) do not need to change for that
migration.

## Architecture

```
pluto_monitor/web/
  service.py   - AcquisitionService: owns hardware lifecycle + background
                 acquisition thread (reuses app.build_receivers /
                 build_transmitter / build_tx_waveform / acquire_once).
  schemas.py   - Pydantic request/response models for the REST API.
  server.py    - FastAPI app: REST endpoints + /ws/metrics WebSocket +
                 static file serving.
  static/      - Plain HTML/CSS/JS dashboard. No CDN, no build step
                 (charts are hand-drawn on <canvas>), so it keeps working
                 without internet access in a lab.
```

Hardware I/O (`pyadi-iio`) is blocking, so it always runs on a single
background thread owned by `AcquisitionService`; the FastAPI/uvicorn event
loop only ever reads the latest snapshot under a lock. This mirrors the
`while True: ...; time.sleep(...)` loop in `app.run_continuous`, just
without blocking the whole process.

## API

- `GET /api/config` - returns the raw YAML config (defaults for the form).
- `GET /api/status` - current lifecycle state, mode, connected radios, groups.
- `GET /api/metrics` - latest snapshot (or `null` if nothing acquired yet).
- `POST /api/start` - body is a `StartRequest` with optional overrides
  (`mode`, `center_frequency_hz`, `sample_rate_hz`, `rx_gain_db`,
  `tx_gain_db`, `tone_frequency_hz`, `sps`, `data_bits`, `update_period_s`).
  Returns `409` if already running/starting.
- `POST /api/stop` - stops acquisition/transmission and closes hardware.
  Returns `409` if not running.
- `WS /ws/metrics` - pushes `{"status": ..., "metrics": ...}` every
  `WS_PUSH_INTERVAL_S` (0.2s by default), independent of the hardware
  acquisition period.

## What's deliberately left out of this iteration

- **Radio-to-group wiring from the UI.** Still edited in the YAML config
  (`clusters.groups`, `clusters.transmitter_serial`), same as
  `scripts/run_local.py`.
- **USB reset.** The MATLAB prototype had this; it was never ported to the
  Python backend (`hardware/` has no reset logic today). Adding it means
  deciding on a mechanism (`pyusb`, `usbreset`, or a udev-based approach)
  and is planned as a follow-up once the core dashboard is validated with
  real hardware.
- **Snapshot/plot export.** `utils/plotting.py` already exports matplotlib
  plots from `MetricHistory` for the console flow; wiring an equivalent
  "export" button/endpoint for the web UI is a follow-up, not core to
  validating the live monitoring flow first.

## Testing without real hardware

`tests/test_web_service.py` stubs `iio`/`adi` and monkeypatches
`build_receivers` / `build_transmitter` / `build_tx_waveform` /
`acquire_once`, so the service's state machine (start/stop/error
handling, snapshot shape, NaN-safety for JSON) is covered without needing
a Pluto connected. Run it like any other test:

```bash
pytest tests/test_web_service.py
```

End-to-end testing (actually opening the dashboard and watching live
data) still requires real Pluto hardware connected to the machine
running `scripts/run_web.py`.
