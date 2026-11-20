# Start API from repo root (kar-yuk\). Needs: docker compose up db -d
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$py = Join-Path $Root "api\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "No api\.venv. Run: cd api; python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
}
Push-Location (Join-Path $Root "api")
try {
    & $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload `
        --reload-exclude ".venv/*" --reload-exclude "**/.venv/**"
} finally {
    Pop-Location
}