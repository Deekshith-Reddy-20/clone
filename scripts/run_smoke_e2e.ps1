# Full-stack smoke: Postgres (Docker) + API (venv) + HTTP checks.
# Run from repo root:  .\scripts\run_smoke_e2e.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root "api\.venv\Scripts\python.exe"
$VenvUvicorn = Join-Path $Root "api\.venv\Scripts\uvicorn.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Missing api\.venv. From api\: python -m venv .venv && .\.venv\Scripts\pip install -r requirements.txt"
}

Set-Location $Root
docker compose up db -d

$env:DATABASE_URL = if ($env:DATABASE_URL) { $env:DATABASE_URL } else { "postgresql+psycopg://karyuk:karyuk@localhost:5432/karyuk" }

Push-Location (Join-Path $Root "api")
& $VenvPython -m alembic upgrade head
Pop-Location

$E2ePort = if ($env:SMOKE_E2E_PORT) { $env:SMOKE_E2E_PORT } else { "8001" }
$E2eBase = "http://127.0.0.1:$E2ePort"
$env:SMOKE_E2E_BASE = $E2eBase

$uvicornJob = Start-Job -ScriptBlock {
    param($Uvicorn, $ApiDir, $Port)
    Set-Location $ApiDir
    & $Uvicorn app.main:app --host 127.0.0.1 --port $Port 2>&1
} -ArgumentList $VenvUvicorn, (Join-Path $Root "api"), $E2ePort

try {
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "$E2eBase/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) {
        Receive-Job $uvicornJob -ErrorAction SilentlyContinue | Write-Host
        throw "API did not become healthy on $E2eBase (is another process using port $E2ePort?)"
    }

    & $VenvPython (Join-Path $Root "scripts\smoke_e2e.py")
    exit $LASTEXITCODE
}
finally {
    Stop-Job $uvicornJob -ErrorAction SilentlyContinue
    Remove-Job $uvicornJob -Force -ErrorAction SilentlyContinue
}