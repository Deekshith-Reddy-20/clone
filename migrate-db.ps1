# Alembic migrate from repo root (kar-yuk\).
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$py = Join-Path $Root "api\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "No api\.venv. Run: cd api; python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
}
Push-Location (Join-Path $Root "api")
try {
    & $py -m alembic upgrade head
} finally {
    Pop-Location
}