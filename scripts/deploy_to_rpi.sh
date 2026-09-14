#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 pi@<rpi-host-or-ip> [remote_dir]"
  echo "Example: $0 pi@192.168.1.21 /home/pi/pluto-cluster-monitor"
  exit 1
fi

TARGET="$1"
REMOTE_DIR="${2:-/home/pi/pluto-cluster-monitor}"

rsync -av --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'data/exports/' \
  --exclude 'data/logs/' \
  ./ "$TARGET:$REMOTE_DIR/"

echo "Uploaded to $TARGET:$REMOTE_DIR"
echo "Then SSH and run:"
echo "  cd $REMOTE_DIR && ./scripts/setup_rpi.sh"
