# PC installation (Linux and Windows)

This covers a development/local-radio PC. Raspberry Pi nodes use
[`scripts/setup_rpi.sh`](09_raspberry_pi_setup.md) instead.

## What has to be installed

| Layer | Linux | Windows |
| --- | --- | --- |
| Pluto USB access | udev rules (`scripts/udev/53-adi-plutosdr-usb.rules`) | ADI PlutoSDR-M2k USB drivers |
| libiio C library **0.2x** | distro package (`libiio`, `libiio0`) | `libiio-0.26.ga0eca0d2-setup.exe` |
| libad9361 (optional, FIR helpers) | distro package | bundled/optional |
| Python 3.10+ and `.venv` | distro `python3` plus Tk for Matplotlib windows | python.org or `winget` |
| Python packages | `pip install -e ".[pluto,local,web,dev]"` | same |
| Node.js (frontend test only) | distro `nodejs` | `winget install OpenJS.NodeJS.LTS` |

The Python `iio` module (`pylibiio`) is a thin ctypes wrapper: it does not ship
the C library. `pyproject.toml` pins `pylibiio<1.0` because pylibiio 1.0 targets
the libiio v1 API (`libiio.so.1`, `libiio1.dll`), while the distro packages,
Raspbian and the Windows installer used by this project provide libiio 0.26.
Without the pin, pip pulls 1.0 and `import iio` fails on libiio 0.26 with
`libiio version 1.x required, found version 0`.

## Linux

```bash
git clone https://github.com/jorojasp/pluto-cluster-monitor.git
cd pluto-cluster-monitor
bash scripts/install_linux.sh            # asks for sudo once
```

The script detects `pacman`, `apt-get`, `dnf` or `zypper`, installs libiio,
libad9361, Python and Node.js, installs the udev rules, creates `.venv`,
installs the project with all extras and lists connected Pluto contexts.
Options: `--skip-system` (no sudo; system parts already done) and `--no-dev`.

Manual equivalent:

```bash
sudo pacman -S --needed libiio libad9361 python tk nodejs   # or apt/dnf equivalents
sudo install -m 0644 scripts/udev/53-adi-plutosdr-usb.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=usb
python3 -m venv .venv
source .venv/bin/activate        # fish: source .venv/bin/activate.fish
python -m pip install -e ".[pluto,local,web,dev]"
```

Reconnect any Pluto that was plugged in before the udev rules were installed.

## Windows

1. Install the [PlutoSDR-M2k USB drivers](https://github.com/analogdevicesinc/plutosdr-m2k-drivers-win/releases).
2. Install [libiio 0.26](https://github.com/analogdevicesinc/libiio/releases/tag/v0.26)
   (`libiio-0.26.ga0eca0d2-setup.exe`, places `libiio.dll` in `System32`). Not 1.x.
3. Install Python 3.10+ (`winget install Python.Python.3.13`).
4. From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
.\.venv\Scripts\Activate.ps1
```

The script refuses to continue until `libiio.dll` is present, then creates the
virtual environment, installs the project and lists detected radios.

## Verify and run

Activate the environment **in every new terminal**, from the repository root:

| Shell | Command |
| --- | --- |
| bash / zsh | `source .venv/bin/activate` |
| fish (CachyOS default) | `source .venv/bin/activate.fish` |
| Windows PowerShell | `.\.venv\Scripts\Activate.ps1` |

Then, on both OSes (stay in the repository root; `run_local.py` opens
`configs/default.yaml` relative to the current directory):

```bash
python scripts/list_radios.py          # serial and URI of each connected Pluto
python -m pytest -q
node tests/test_frontend_history.mjs
python scripts/run_local.py            # local USB radios, configs/default.yaml (transmits)
python scripts/run_web.py --config configs/default.yaml   # same radios in the browser
```

Put the serials reported by `list_radios.py` into `configs/default.yaml`
(`clusters.groups.*.radio_serials`, `clusters.transmitter_serial`).
Another file can be used with `--config`, for example `configs/local.yaml`, which
git ignores. A `local:` context with serial `UNKNOWN` is the PC's
own sensors, not a Pluto.

## Troubleshooting

- `iio_info -s` (Linux, `libiio-utils`/`libiio`) lists contexts outside Python.
  If it sees `usb:` entries but only as root, the udev rules are not active.
- A Pluto also appears as a USB network adapter at `ip:192.168.2.1`; discovery
  prefers `usb:` URIs when both exist.
- `ModuleNotFoundError: No module named 'iio'`: the system Python is running, not
  the one in `.venv`. The pacman `libiio` package is only the C library. Activate
  the environment (table above) or run `.venv/bin/python scripts/list_radios.py`.
- fish prints `'case' builtin` errors on activation: use `activate.fish`.
- `undefined symbol: iio_get_backends_count` (Linux): the libiio C library is missing.
- `libiio version 1.x required, found version 0`: pylibiio 1.0 is installed; run
  `python -m pip install "pylibiio>=0.23.1,<1.0"`.
- Only `local:` is listed: no Pluto is visible. Check `lsusb` for `0456:b673`; if
  it is absent, check the cable (must carry data), port and power first.
- `run_local.py` shows no window: Matplotlib fell back to `agg` because Tk is
  missing. Install `tk` (pacman), `python3-tk` (apt, zypper) or `python3-tkinter` (dnf).

## Installation log: CachyOS laptop, 2026-11-20 to 2026-11-24

Migration of the Windows-developed checkout to a Linux PC (CachyOS, Python 3.14):

1. Checked the repo for Windows leftovers: no CRLF files (`.gitattributes`
   enforces LF), no hard-coded `C:\` paths; configs use relative paths and
   UTF-8 is set explicitly when reading YAML.
2. `python3 -m venv .venv` and `pip install -e ".[pluto,local,web,dev]"`:
   all wheels available for Python 3.14 (NumPy 2.5, SciPy 1.18, FastAPI 0.165).
3. pip resolved `pylibiio 1.0` through pyadi-iio; it requires libiio v1, while
   Arch/CachyOS ships libiio 0.26. Pinned `pylibiio>=0.23.1,<1.0` (0.25) in the
   `pluto` extra.
4. Python tests failed at import until the C library was present; the frontend
   test passed with system Node.js.
5. Installed `libiio` 0.26 and `libad9361` with pacman (2026-11-20) and the udev
   rules from `scripts/udev/` (2026-11-24).
6. Added `scripts/install_linux.sh` and `scripts/install_windows.ps1` so both
   platforms install with one command.
7. `list_radios.py` failed with `No module named 'iio'`: it ran with the system
   Python, and the documented `activate` script does not work in fish. Documented
   `activate.fish`; `list_radios.py` then ran correctly.
8. Verified: 29 Python tests and the frontend test pass, and
   `install_linux.sh --skip-system` completes. One Pluto Rev.C
   (firmware v0.32) was then detected over `usb:` and `ip:` and its USB context
   opened without root; later all five radios of `configs/default.yaml` were
   detected. Not yet verified: `run_local.py` end to end, the sudo part of
   `install_linux.sh`, non-pacman package names, and the Windows script.
