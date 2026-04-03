# Pluto Cluster Monitor

Python migration of a multi-ADALM Pluto SDR monitoring system originally implemented in MATLAB.

## Current goal
Build a modular backend capable of:
- controlling multiple Pluto SDR receivers
- optionally controlling one Pluto SDR transmitter
- computing received power and basic SNR metrics
- identifying strongest and weakest receivers by group
- exporting measurements for later analysis

## Project status
This repository is the first structured Python version of the original MATLAB prototype.

## Planned features
- multi-receiver monitoring
- cluster-based comparison
- SineWave mode
- BPSK / QPSK / 16QAM processing
- export of plots and snapshots
- future distributed TX/RX architecture

## Repository structure
- `configs/`: YAML configuration files
- `docs/`: architecture and migration notes
- `scripts/`: runnable entrypoints
- `src/pluto_monitor/`: application source code
- `tests/`: unit tests
- `data/`: runtime data, logs, and exports

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .