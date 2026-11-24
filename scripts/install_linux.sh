#!/usr/bin/env bash
# PC installer for Linux (Arch/CachyOS/Manjaro, Debian/Ubuntu, Fedora, openSUSE).
# Raspberry Pi nodes keep using scripts/setup_rpi.sh.
#
# Usage: bash scripts/install_linux.sh [--skip-system] [--no-dev]
#   --skip-system  do not use sudo (libiio, libad9361 and udev rules already installed)
#   --no-dev       install only runtime extras (pluto, local, web)
set -euo pipefail

SKIP_SYSTEM=0
EXTRAS="pluto,local,web,dev"
for arg in "$@"; do
  case "$arg" in
    --skip-system) SKIP_SYSTEM=1 ;;
    --no-dev) EXTRAS="pluto,local,web" ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

install_system_packages() {
  if command -v pacman >/dev/null; then
    sudo pacman -S --needed --noconfirm libiio libad9361 python tk nodejs
  elif command -v apt-get >/dev/null; then
    sudo apt-get update
    # libiio-utils provides iio_info; package names follow Debian 12/13 and Ubuntu 22.04+.
    sudo apt-get install -y python3 python3-venv python3-pip python3-tk \
      libiio0 libiio-utils libad9361-0 nodejs
  elif command -v dnf >/dev/null; then
    sudo dnf install -y python3 python3-pip python3-tkinter libiio libiio-utils libad9361 nodejs
  elif command -v zypper >/dev/null; then
    sudo zypper install -y python3 python3-pip python3-tk libiio0 libiio-tools libad9361-0 nodejs
  else
    echo "Unsupported package manager. Install libiio 0.2x and libad9361 manually," >&2
    echo "then rerun with --skip-system." >&2
    exit 1
  fi
}

install_udev_rules() {
  sudo install -m 0644 scripts/udev/53-adi-plutosdr-usb.rules /etc/udev/rules.d/
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=usb
}

if [[ "$SKIP_SYSTEM" == 0 ]]; then
  install_system_packages
  install_udev_rules
fi

PYTHON="${PYTHON:-python3}"
"$PYTHON" - <<'EOF'
import sys
if sys.version_info < (3, 10):
    sys.exit(f"Python 3.10+ required, found {sys.version.split()[0]}")
EOF

[[ -d .venv ]] || "$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[$EXTRAS]"
mkdir -p data/logs data/exports

.venv/bin/python - <<'EOF'
import adi, iio, numpy, scipy, yaml, fastapi, uvicorn
print(f"libiio {'.'.join(map(str, iio.version[:2]))} OK, pyadi-iio OK")
radios = iio.scan_contexts()
print(f"Pluto/IIO contexts detected: {len(radios)}")
for uri, desc in radios.items():
    print(f"  {uri}  {desc}")
EOF

echo
echo "Setup complete. Activate the environment before running anything:"
echo "  bash/zsh: source .venv/bin/activate"
echo "  fish:     source .venv/bin/activate.fish"
echo "List radios: python scripts/list_radios.py"
echo "Without activating (any shell): .venv/bin/python scripts/list_radios.py"
echo "Run tests:   python -m pytest -q && node tests/test_frontend_history.mjs"
echo "If a Pluto was already plugged in, unplug and reconnect it once."
