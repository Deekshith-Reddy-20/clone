# Start ngrok for Karyuk API (:8000) and sync PUBLIC_API_BASE_URL in .env
# Usage (repo root):  .\scripts\start-ngrok.ps1

$ErrorActionPreference = "Stop"
$Root = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { Get-Location }
$EnvFile = Join-Path $Root ".env"

if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    Write-Error "ngrok not found. Install from https://ngrok.com/download and run: ngrok config add-authtoken <token>"
}

try {
    Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
    Write-Error "Local API is not running on :8000. Start it first: .\serve-api.ps1"
}

$existing = $null
try {
    $existing = (Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2).tunnels | Where-Object { $_.config.addr -match "8000" } | Select-Object -First 1
} catch {
    $existing = $null
}

if ($existing) {
    Write-Host "Reusing existing ngrok tunnel (do not start a second ngrok — causes ERR_NGROK_334)."
} elseif (-not $existing) {
    Write-Host "Starting ngrok http 8000 (new window recommended)..."
    Start-Process -FilePath "ngrok" -ArgumentList "http", "8000" -WindowStyle Normal
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            $existing = (Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels").tunnels | Where-Object { $_.config.addr -match "8000" } | Select-Object -First 1
            if ($existing) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) { Write-Error "ngrok did not start within 30s. Check ngrok authtoken." }
}

$public = ($existing | Where-Object { $_.public_url -like "https://*" } | Select-Object -First 1).public_url
if (-not $public) { $public = $existing.public_url }

Write-Host "Public URL: $public"

if (Test-Path $EnvFile) {
    $text = Get-Content $EnvFile -Raw
    if ($text -match "(?m)^PUBLIC_API_BASE_URL=.*") {
        $text = $text -replace "(?m)^PUBLIC_API_BASE_URL=.*", "PUBLIC_API_BASE_URL=$public"
    } else {
        $text += "`nPUBLIC_API_BASE_URL=$public`n"
    }
    Set-Content -Path $EnvFile -Value $text.TrimEnd() -NoNewline
    Write-Host "Updated $EnvFile"
} else {
    Write-Warning ".env not found at $EnvFile"
}

$headers = @{ "ngrok-skip-browser-warning" = "1" }
try {
    $h = Invoke-RestMethod -Uri "$public/health" -Headers $headers -TimeoutSec 15
    Write-Host "Tunnel OK: $($h | ConvertTo-Json -Compress)"
} catch {
    Write-Warning "Could not reach $public/health — wait a few seconds and retry, or click through ngrok browser warning once."
}

Write-Host ""
Write-Host "Next:"
Write-Host "  1. Restart API: .\serve-api.ps1"
Write-Host "  2. Test in browser: $public/health"
Write-Host "  3. If you see ngrok 'Visit Site' — click it once (Exotel webhooks usually still work)."