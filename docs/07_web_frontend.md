# Distributed web frontend

## Runtime flow

`web/server.py` picks the provider from the configuration file:

- `clusters` section: `AcquisitionService` (`web/service.py`), radios on this PC.
- `network` section: `DistributedService`, with `DistributedRxCoordinator` and
  `LocalTxController`. The server runs on `txpi`, which also owns the TX Pluto.
  `rxpi1` and `rxpi2` do USB acquisition and DSP; only JSON metrics cross the LAN.

Start and Stop do not block status requests or the browser updates. If local
acquisition fails, the transmitter is stopped.

The static HTML/CSS/JavaScript needs no CDN or frontend build. Group A is blue
and group B orange. Serial inventories are reported even while acquisition is
idle; missing radios and stale/offline nodes are labeled separately.

## Start

```bash
python scripts/run_web.py --config configs/default.yaml                    # this PC
python scripts/run_web.py --config configs/rpi_server.yaml --host 0.0.0.0  # Raspberry Pi
```

The default host is 127.0.0.1. There is no login, so expose the server only on a
private network. The distributed case requires the RX processes described in the
[Raspberry Pi guide](09_raspberry_pi_setup.md). The CLI default is the server
configuration. To select another file set `--config`; direct uvicorn launches
can instead set `PLUTO_MONITOR_CONFIG`.

## API

| Route | Behavior |
| --- | --- |
| `GET /` | Dashboard |
| `GET /api/config` | Base app/RF settings and the available modes for the form |
| `GET /api/status` | Global lifecycle, per-node inventories/age, TX state, last session ID/path |
| `GET /api/metrics` | Latest per-group metrics, individual timestamps and sequence numbers |
| `POST /api/start` | Start RX nodes and optionally TX; body accepts RF/mode/timing overrides and `transmit_enabled` |
| `POST /api/stop` | Stop TX and RX; return to idle when all nodes acknowledge |
| `WS /ws/metrics` | Latest status and metrics every 0.2 seconds |

Settings are applied on Start. The frontend disables configuration controls
while active. With Enable transmitter unchecked, Start acquires only the
background; the TX remains off. Radio serials/group wiring stay in YAML.

## Charts and persistence

Charts use acquisition timestamps, not WebSocket message count. Repeated
snapshots do not create extra points, and groups update independently. The
vertical range spans at least 20 dB and only expands during a session; a large
startup transient can therefore visually flatten subsequent small changes.
Axes show elapsed seconds and relative IQ dB. Estimated noise/error is labeled
as such, and missing estimates create gaps.

The coordinator records every received metrics message in a unique JSONL
session, with effective RX settings, sequence, source timestamp and server
receive time. Start/stop metadata distinguish TX-off and TX-on sessions.
Raw IQ is not persisted. Logs stay under `runtime.log_dir`, ignored by Git.

## Current limitations

Session logs (JSONL) exist only in distributed mode. UDP commands to the nodes
are not authenticated. Server state may retain the last
reported node state; inspect `age_s` (the UI marks inventory stale after 10 s).
The latest metric snapshot can remain after Stop; it is not live acquisition.
After recovery, use Stop to clear the lifecycle error and repeat the session.
Automatic process restart, USB reset and snapshot export are not implemented;
raw-IQ capture (`runtime.save_iq`) is available in local modes only. See [experimental limits](06_experiments_and_results.md).
