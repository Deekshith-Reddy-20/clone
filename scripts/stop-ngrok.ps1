# Stop local ngrok agent (free plan: only one tunnel per reserved URL)
Get-Process ngrok -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Stopping ngrok pid $($_.Id)"
    Stop-Process -Id $_.Id -Force
}
if (-not (Get-Process ngrok -ErrorAction SilentlyContinue)) {
    Write-Host "No ngrok process running. You can run: ngrok http 8000"
}