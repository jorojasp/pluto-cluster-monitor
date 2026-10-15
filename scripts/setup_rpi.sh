#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-receiver}"
case "$ROLE" in
  receiver|server) ;;
  *) echo "Usage: bash scripts/setup_rpi.sh [receiver|server]" >&2; exit 1 ;;
esac

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Tested on 32-bit Raspbian 13 (Trixie). Use distribution-built ARM packages.
sudo apt update
sudo apt install -y \
  git rsync \
  python3 python3-venv python3-pip python3-setuptools python3-wheel \
  python3-numpy python3-scipy python3-yaml \
  libiio0 libiio-utils python3-libiio libad9361-0

if [[ "$ROLE" == server ]]; then
  sudo apt install -y python3-fastapi python3-uvicorn
fi

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --no-deps -r requirements-rpi.txt
python -m pip install --no-deps --no-build-isolation -e .
python -c 'import adi, iio, numpy, scipy, yaml; print("SDR dependencies OK")'
if [[ "$ROLE" == server ]]; then
  python -c 'import fastapi, pydantic, uvicorn; print("Web dependencies OK")'
fi

echo "Setup complete: $ROLE profile"
echo "Activate with: source $REPO_DIR/.venv/bin/activate"
echo "Check radios with: iio_info -s"
echo "See docs/09_raspberry_pi_setup.md for startup and recovery."
