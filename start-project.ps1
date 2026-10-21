$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host 'Python is not installed. Install Python 3.10+ from https://python.org, then run this script again.' -ForegroundColor Red
    exit 1
}
if (-not (Test-Path "$root\backend\.venv\Scripts\python.exe")) {
    & py -m venv "$root\backend\.venv"
}
& "$root\backend\.venv\Scripts\python.exe" -m pip install -r "$root\backend\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Some optional AI training packages could not be downloaded. Starting DMERS with its built-in advisory fallback.' -ForegroundColor Yellow
}
Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$root\backend'; & '.\.venv\Scripts\python.exe' -m flask --app run run --host 127.0.0.1 --port 5000"
Set-Location "$root\frontend"
if (-not (Test-Path 'node_modules')) { npm install }
npm run dev
