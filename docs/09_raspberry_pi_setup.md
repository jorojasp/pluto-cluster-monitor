# Raspberry Pi installation and recovery

## Profiles

The tested lab OS is Raspbian 13 (Trixie), armv7l, with Python 3.13.5. Install
NumPy, SciPy and libiio through APT, then reuse those packages in a virtual
environment. This avoids compiling scientific or web dependencies on a Pi 2.

From a checkout at the repository root:

```bash
bash scripts/setup_rpi.sh receiver  # rxpi1 and rxpi2
bash scripts/setup_rpi.sh server    # txpi
```

The setup script targets this Trixie package naming (`libad9361-0`). Other OS
versions may need different package names. It creates `.venv` in the checkout
and installs this package and pyadi-iio without pulling scientific dependencies
from pip. The server profile additionally installs FastAPI/Uvicorn via APT.
The receiver profile does not install Matplotlib or the web stack.

## Configuration and startup

Confirm identities before changing wiring:

```bash
hostname
iio_info -s
vcgencmd get_throttled
```

Use the serials in each receiver's `radios` list. Keep `node.id` equal to the
corresponding `network.receiver_nodes[].id` in the server config. Confirm that
`txpi.local`, `rxpi1.local` and `rxpi2.local` resolve from the relevant machines.

Start receivers first:

```bash
source .venv/bin/activate
# On rxpi1:
python -m pluto_monitor.nodes.rx_node --config configs/rpi_group_a.yaml
# On rxpi2, use configs/rpi_group_b.yaml instead.
```

Then start the web coordinator and TX controller on txpi:

```bash
source .venv/bin/activate
python scripts/run_web.py --config configs/rpi_server.yaml --port 8000
```

Open `http://txpi.local:8000`. Check that all group serials are detected before
Start. The sample config leaves TX disabled and uses -40 dB TX gain; the later
proximity experiments used -30 dB. Follow the [validation protocol](08_measurement_validation.md).

## Existing laboratory deployment

The manually deployed copies currently live in `~/pluto-monitor-deploy` and
use the external `~/pluto-venv` environment. They were launched detached from
SSH; PID files and output are in `logs/service.pid` and `logs/service.log`.
They do not automatically restart after reboot. The commands above describe
reproducing the setup from a fresh checkout; they must not be launched alongside
an already running laboratory process on the same ports/radios.

## Transfer

On a machine with Bash, rsync and SSH:

```bash
bash scripts/deploy_to_rpi.sh jorge@rxpi1 /home/jorge/pluto-cluster-monitor
```

This copies source while preserving remote runtime data, virtual environments
and `configs/*.local.yaml` overrides. It does not install, stop or restart
processes. Inspect the target path before transferring to an existing checkout.
Use explicit target directories; do not mix the checkout and laboratory copy.

## LAN recovery

A receiver process can exit after a DNS or UDP failure. Reconnecting the cable
alone does not restart it. Check `hostname`, `getent hosts txpi.local`, the
receiver process and its log. Restart the missing RX process, then press Stop
on the server to return to idle. Wait for fresh node state and serial inventory
before repeating the entire interrupted run. Do not compare a stale group's
last snapshot against another group's fresh metrics.

## Limits

The two RX Pis currently report undervoltage. Continue only with the understood
experimental limitation; adequate power is still needed for reliable long runs
and additional radios. Do not remove the microSD while powered. Persistent
service management, watchdogs and automated network recovery remain pending.
