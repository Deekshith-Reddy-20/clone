# Full local integration: migrations, smoke, e2e (optional), web build, inbound voice test.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Venv = Join-Path $Root "api\.venv\Scripts\python.exe"
if (-not (Test-Path $Venv)) { throw "Run: cd api; python -m venv .venv; pip install -r requirements.txt" }

Write-Host "1) API smoke (sqlite)..." -ForegroundColor Cyan
& $Venv (Join-Path $Root "scripts\run_smoke.py")
if ($LASTEXITCODE -ne 0) { throw "run_smoke failed" }

if (docker info 2>$null) {
    Write-Host "2) E2E smoke (postgres + HTTP)..." -ForegroundColor Cyan
    & (Join-Path $Root "scripts\run_smoke_e2e.ps1")
    if ($LASTEXITCODE -ne 0) { throw "smoke_e2e failed" }
} else {
    Write-Host "2) Skip e2e (docker not available)" -ForegroundColor Yellow
}

Write-Host "3) Web build..." -ForegroundColor Cyan
Push-Location (Join-Path $Root "web")
npm run build
if ($LASTEXITCODE -ne 0) { throw "web build failed" }
Pop-Location

Write-Host "4) Inbound voice (TestClient)..." -ForegroundColor Cyan
& $Venv (Join-Path $Root "scripts\test_inbound_voice.py")
if ($LASTEXITCODE -ne 0) { throw "test_inbound_voice failed" }

Write-Host ""
Write-Host "=== Integration green ===" -ForegroundColor Green
Write-Host "Live call: .\scripts\start-inbound-stack.ps1  (API + ngrok only; voice agent optional for gemini mode)"
Write-Host "Exotel applet: see /v1/ops/status -> exotel_inbound_voice_url"