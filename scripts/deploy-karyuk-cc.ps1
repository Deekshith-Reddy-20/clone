# Sync this repo to Hetzner: ssh Host "karyuk" → /root/karyuk-cc
# Usage (repo root):  .\scripts\deploy-karyuk-cc.ps1
# Optional:           .\scripts\deploy-karyuk-cc.ps1 -IncludeEnv

param(
    [switch]$IncludeEnv
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Remote = "karyuk"
$RemoteDir = "/root/karyuk-cc"
$Archive = Join-Path $env:TEMP "karyuk-cc-deploy.tgz"

Write-Host "=== Deploy to ${Remote}:${RemoteDir} ===" -ForegroundColor Cyan

$paths = @(
    "api", "web", "voice", "scripts", "docs", "infra",
    "docker-compose.yml", ".gitignore", "serve-api.ps1", "migrate-db.ps1",
    "run-full-integration.ps1"
)
$excludes = @(
    "node_modules", ".venv", "voice/.venv", "web/dist", "scripts/out", ".git", "__pycache__"
)
if (-not $IncludeEnv) { $excludes += ".env" }

$tarArgs = @("-czf", $Archive)
foreach ($ex in $excludes) { $tarArgs += "--exclude=$ex" }
$tarArgs += @("-C", $Root)
foreach ($p in $paths) {
    if (Test-Path (Join-Path $Root $p)) { $tarArgs += $p }
}

& tar @tarArgs
if (-not (Test-Path $Archive)) { throw "tar failed to create $Archive" }
Write-Host "Archive: $((Get-Item $Archive).Length) bytes"

ssh -o BatchMode=yes $Remote "mkdir -p $RemoteDir"
scp $Archive "${Remote}:/tmp/karyuk-cc-deploy.tgz"
ssh $Remote @"
cd $RemoteDir && tar -xzf /tmp/karyuk-cc-deploy.tgz && rm -f /tmp/karyuk-cc-deploy.tgz
chmod +x scripts/server-setup-karyuk-cc.sh 2>/dev/null || true
ls -la | head -20
"@
Remove-Item -Force $Archive

if (-not $IncludeEnv) {
    Write-Host "Skipped .env — copy: scp .env ${Remote}:${RemoteDir}/.env" -ForegroundColor Yellow
}

Write-Host "Done. ssh $Remote 'cd $RemoteDir && bash scripts/server-setup-karyuk-cc.sh'"