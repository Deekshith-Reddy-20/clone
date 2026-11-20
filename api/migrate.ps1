# Run from api\:  .\migrate.ps1
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
& (Join-Path $here ".venv\Scripts\python.exe") -m alembic upgrade head