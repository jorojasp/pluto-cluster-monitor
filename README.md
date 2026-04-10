# Pluto Cluster Monitor

Python migration of a multi-ADALM Pluto SDR monitoring system originally implemented in MATLAB.

## Overview

This project develops a scalable multi-SDR platform for real-time analysis of wireless communication signals using ADALM-Pluto radios.

The original system was implemented in MATLAB and demonstrated continuous monitoring of received power and Signal-to-Noise Ratio (SNR), automatic identification of the strongest and weakest receivers, support for multiple transmission modes, and flexible grouping of receivers into logical clusters for comparative analysis.

The current stage of the project focuses on porting the backend from MATLAB to Python. The goal is to preserve the validated logic of the original prototype while improving modularity, maintainability, and long-term deployability.

## Current goal

Build a modular backend capable of:

- controlling multiple Pluto SDR receivers
- controlling one Pluto SDR transmitter
- computing received power and SNR metrics
- identifying strongest and weakest receivers by group
- comparing receiver groups
- storing short measurement histories
- exporting plots and measurements for later analysis

## Project status

This repository contains the first structured Python backend derived from the original MATLAB prototype.

The current development focus is on:

- hardware discovery and stable radio identification
- continuous acquisition for SineWave mode
- received power and SNR estimation
- strongest/weakest receiver monitoring
- group-based comparison
- history tracking and plot export

At this stage, the Python version should be understood as a backend reconstruction of the validated MATLAB system, not yet as a full replacement of the original interactive interface.

## Planned features

- multi-receiver monitoring
- cluster-based comparison
- SineWave mode
- BPSK / QPSK / 16QAM processing
- export of plots and snapshots
- improved hardware discovery and mapping
- future distributed TX/RX architecture
- possible embedded Linux deployment

## Repository structure

- `configs/`: YAML configuration files
- `docs/`: technical and thesis-oriented documentation
- `scripts/`: runnable entrypoints
- `src/pluto_monitor/`: application source code
- `tests/`: unit tests
- `data/`: runtime data, logs, and exports

## Documentation

Detailed project documentation is available in [`docs/`](docs/).

Suggested reading order:

1. `docs/01_problem_statement.md`
2. `docs/02_system_architecture.md`
3. `docs/03_matlab_prototype.md`
4. `docs/04_python_migration.md`
5. `docs/05_signal_processing.md`
6. `docs/06_experiments_and_results.md`

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .