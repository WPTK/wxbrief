# Build dist\wxbrief.exe with PyInstaller and smoke-test it. Run from anywhere; needs the project venv or any
# Python 3.12 with the project and PyInstaller installed (pip install -e ".[dev]").
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

& $python -m PyInstaller wxbrief.spec --noconfirm --clean --workpath .pyi-build --distpath dist
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }

& .\dist\wxbrief.exe --selftest
if ($LASTEXITCODE -ne 0) { throw "selftest failed ($LASTEXITCODE)" }

Get-FileHash .\dist\wxbrief.exe -Algorithm SHA256 | ForEach-Object { "$($_.Hash.ToLower())  wxbrief.exe" }
