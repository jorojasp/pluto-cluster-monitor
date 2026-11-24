# PC installer for Windows 10/11.
# Usage (from the repository root, regular PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1 [-NoDev]
param([switch]$NoDev)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

# 1. libiio C library (libiio.dll) - not installable through pip.
$libiio = Join-Path $env:WINDIR "System32\libiio.dll"
if (-not (Test-Path $libiio)) {
    Write-Host "libiio.dll not found. Install these first, then rerun this script:" -ForegroundColor Yellow
    Write-Host "  1. Pluto USB drivers: https://github.com/analogdevicesinc/plutosdr-m2k-drivers-win/releases"
    Write-Host "  2. libiio 0.26 (libiio-0.26.ga0eca0d2-setup.exe): https://github.com/analogdevicesinc/libiio/releases/tag/v0.26"
    Write-Host "Do not use libiio 1.x: the project pins the 0.x Python bindings."
    exit 1
}

# 2. Python 3.10+ through the py launcher (or python on PATH).
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
& $py -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.10+ required: https://www.python.org/downloads/ (or: winget install Python.Python.3.13)" -ForegroundColor Red
    exit 1
}

# 3. Virtual environment and project.
if (-not (Test-Path ".venv")) { & $py -m venv .venv }
$venvPy = ".\.venv\Scripts\python.exe"
$extras = if ($NoDev) { "pluto,local,web" } else { "pluto,local,web,dev" }
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -e ".[$extras]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
New-Item -ItemType Directory -Force -Path data\logs, data\exports | Out-Null

# 4. Verify bindings and list connected radios.
& $venvPy -c @"
import adi, iio, numpy, scipy, yaml, fastapi, uvicorn
print('libiio', '.'.join(map(str, iio.version[:2])), 'OK, pyadi-iio OK')
radios = iio.scan_contexts()
print('Pluto/IIO contexts detected:', len(radios))
for uri, desc in radios.items():
    print(' ', uri, desc)
"@

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "Optional: Node.js for the frontend test (winget install OpenJS.NodeJS.LTS)" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Setup complete. Activate with: .\.venv\Scripts\Activate.ps1"
Write-Host "List radios: python scripts\list_radios.py"
