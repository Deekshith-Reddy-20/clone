# Run from api\:  .\serve.ps1
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
& (Join-Path $here ".venv\Scripts\python.exe") -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload