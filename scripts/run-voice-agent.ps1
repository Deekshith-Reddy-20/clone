# Start the LiveKit voice worker (run in a separate terminal while testing inbound calls).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Voice = Join-Path $Root "voice"
$Venv = Join-Path $Voice ".venv"

if (-not (Test-Path $Venv)) {
    Write-Host "Creating voice venv and installing dependencies..."
    python -m venv $Venv
    & "$Venv\Scripts\pip.exe" install -r (Join-Path $Voice "requirements.txt")
}

Set-Location $Voice
Write-Host "Starting Karyuk voice agent (Ctrl+C to stop)..."
& "$Venv\Scripts\python.exe" agent.py dev