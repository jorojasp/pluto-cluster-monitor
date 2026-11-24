# Pluto Cluster Monitor

A Python platform for monitoring groups of ADALM-Pluto SDR receivers, migrated
from a MATLAB prototype. It compares received power and estimated SNR using
one transmitter and multiple logical receiver groups.

## Current architecture

The distributed web setup uses three Raspberry Pi 2 Model B boards:

| Host | Role | Config | Attached radios |
| --- | --- | --- | --- |
| `txpi` | Web server, UDP coordinator and transmitter | `configs/rpi_server.yaml` | One TX |
| `rxpi1` | Group A acquisition and DSP | `configs/rpi_group_a.yaml` | A1 and A2 |
| `rxpi2` | Group B acquisition and DSP | `configs/rpi_group_b.yaml` | B1 and B2 |

Receiver serial numbers stay in the receiver's YAML. The server distributes RF
settings and Start/Stop commands over UDP; each receiver returns per-radio
metrics and a periodically refreshed hardware inventory. Add radios to the
appropriate receiver config to expand a group; throughput and power delivery
must then be checked experimentally.

SineWave, BPSK, QPSK, 16QAM and [coded OFDM](docs/11_ofdm.md) have TX/RX code paths
and synthetic tests. The
digital modes also report BER. All nodes must run the same version, because the
payload and frame layout are shared.
**Only SineWave has completed the current physical gain/proximity checks.**
Digital modulation validation on this distributed hardware remains pending.

Radios attached to one PC can be used in two ways with `configs/default.yaml`:
`scripts/run_local.py` (console and Matplotlib) or `scripts/run_web.py` (browser).
The web server picks the local or distributed provider from the configuration.

## Start the distributed system

See [Raspberry Pi setup](docs/09_raspberry_pi_setup.md) for OS dependencies and
installation. From the repository root on each node, activate its environment:

```bash
source .venv/bin/activate
```

On `rxpi1`:

```bash
python -m pluto_monitor.nodes.rx_node --config configs/rpi_group_a.yaml
```

On `rxpi2`:

```bash
python -m pluto_monitor.nodes.rx_node --config configs/rpi_group_b.yaml
```

On `txpi`:

```bash
python scripts/run_web.py --config configs/rpi_server.yaml --host 0.0.0.0 --port 8000
```

Open `http://txpi.local:8000` from another machine on the same LAN. **There is no
login:** with `--host 0.0.0.0` anyone on that network can start the transmitter, so
use a private lab network. Without `--host` only the local machine can connect.
The sample
server configuration starts with TX disabled and TX gain -40 dB. Check
**Enable transmitter** before Start when transmission is wanted. Uncheck it
for a background measurement. Settings apply to the next Start.

The dashboard displays English labels, serials by group, power/SNR tables,
and timestamped group charts with distinct colors. Every acquisition session
is recorded as JSONL under `data/logs/`; these files contain metrics, not raw IQ.
`GET /api/status` includes the current/last session ID and log path.

## PC installation and tests

Python 3.10+ and the libiio 0.2x C library are required. One-command setup
(details, drivers and troubleshooting in [PC installation](docs/10_pc_installation.md)):

```bash
bash scripts/install_linux.sh                                   # Linux
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1   # Windows
```

Manual setup after installing libiio (and, on Linux, the udev rules):

```bash
python -m venv .venv
# Linux/macOS (bash/zsh): source .venv/bin/activate
# Linux/macOS (fish): source .venv/bin/activate.fish
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[pluto,local,web,dev]"
python -m pytest -q
node tests/test_frontend_history.mjs
```

For local USB radios on the PC (**both transmit** unless `app.transmit_enabled` is
false in the config or the box is unchecked in the browser):

```bash
python scripts/run_local.py --config configs/default.yaml
python scripts/run_web.py --config configs/default.yaml   # http://127.0.0.1:8000
```

Set `runtime.save_iq: true` to keep raw captures under `data/raw/` (local modes).

## Measurement limits

- Power is relative to IQ sample units, **not calibrated dBm**, and includes DC.
- SineWave estimates a tone and its residual. Receiver spurs can also yield a
  tone estimate with TX off; SNR alone does not identify the intended source.
- Digital SNR compares symbols with the known payload; estimated error includes
  distortion and synchronization error, not only thermal noise.
- Receivers discard the startup transient and stale queued buffers. Variable DC
  offsets, particularly in A2, remain unresolved for SineWave and total power.
- The lab receiver Pis reported undervoltage during these tests. Long-term
  stability and additional-radio capacity have not been established.
- RX nodes survive LAN/name-resolution failures, but automatic startup is not
  implemented. Press Stop before repeating an interrupted measurement.

## Repository map

- `src/pluto_monitor/hardware/`: serial discovery and radio access.
- `src/pluto_monitor/dsp/`: waveform generation and metric estimators;
  `modes.py` is the registry where new modes are added.
- `src/pluto_monitor/services/`: acquisition and group comparison.
- `src/pluto_monitor/nodes/`, `network/`: distributed roles and UDP messages.
- `src/pluto_monitor/web/`: API, lifecycle and static browser dashboard.
- `configs/`: local and distributed YAML configurations.
- `scripts/`: setup, transfer, discovery and application entrypoints.
- `tests/`: hardware-free Python regressions and frontend history checks.
- `data/`: ignored runtime logs, captures and exports.

## Documentation

1. [Problem statement](docs/01_problem_statement.md)
2. [Architecture and migration background](docs/02_system_architecture.md)
3. [MATLAB prototype](docs/03_matlab_prototype.md)
4. [Python migration background](docs/04_python_migration.md)
5. [Signal processing and units](docs/05_signal_processing.md)
6. [Experiments and results](docs/06_experiments_and_results.md)
7. [Distributed web frontend and API](docs/07_web_frontend.md)
8. [Measurement corrections and validation protocol](docs/08_measurement_validation.md)
9. [Raspberry Pi setup and recovery](docs/09_raspberry_pi_setup.md)
10. [PC installation on Linux and Windows](docs/10_pc_installation.md)
11. [Coded OFDM](docs/11_ofdm.md)
