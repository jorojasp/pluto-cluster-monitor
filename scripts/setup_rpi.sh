#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install -y \
  git rsync \
  python3 python3-venv python3-pip \
  python3-numpy python3-scipy python3-yaml \
  libiio0 libiio-utils python3-libiio libad9361-iio0

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install --no-deps pyadi-iio
python -m pip install --no-deps -e .

cat <<'TXT'

Setup finished.
Activate the environment with:
  source .venv/bin/activate

Check Pluto visibility with:
  iio_info -s
  python scripts/list_radios.py
TXT
