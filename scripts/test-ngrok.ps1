# Quick check: local API + ngrok tunnel + .env match
$Root = Split-Path -Parent $PSScriptRoot
$envLine = Select-String -Path (Join-Path $Root ".env") -Pattern "^PUBLIC_API_BASE_URL=(.+)$" -ErrorAction SilentlyContinue
$configUrl = if ($envLine) { $envLine.Matches[0].Groups[1].Value.Trim() } else { "(missing)" }

Write-Host "PUBLIC_API_BASE_URL in .env: $configUrl"

try {
    $tunnels = (Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels").tunnels
    $https = ($tunnels | Where-Object { $_.public_url -like "https://*" } | Select-Object -First 1).public_url
    Write-Host "ngrok live URL:            $https"
    if ($configUrl -ne $https) {
        Write-Warning "MISMATCH — run .\scripts\start-ngrok.ps1 or update .env"
    }
} catch {
    Write-Warning "ngrok not running (no :4040). Run: ngrok http 8000"
}

try {
    $local = Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 3
    Write-Host "Local API:                 OK $($local.status)"
} catch {
    Write-Warning "Local API down on :8000 — run .\serve-api.ps1"
}

if ($configUrl -match "^https://") {
    $headers = @{ "ngrok-skip-browser-warning" = "1" }
    try {
        $remote = Invoke-RestMethod "$configUrl/health" -Headers $headers -TimeoutSec 15
        Write-Host "Public /health:            OK $($remote.status)"
    } catch {
        Write-Warning "Public URL failed: $($_.Exception.Message)"
    }
}