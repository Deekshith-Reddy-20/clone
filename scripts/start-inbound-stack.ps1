# Run API, ngrok, and voice agent in separate windows (do not chain in one terminal).
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "Starting Karyuk inbound stack in 3 windows..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root'; .\serve-api.ps1"
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root'; .\scripts\start-ngrok.ps1"
Start-Sleep -Seconds 3
$mode = "exotel_gemini"
try {
    $t = Invoke-RestMethod "http://127.0.0.1:8000/v1/ops/status" -ErrorAction Stop
    $mode = $t.telephony.inbound_voice_mode
} catch {}
if ($mode -eq "livekit") {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root'; .\scripts\run-voice-agent.ps1"
    Write-Host "Started LiveKit voice agent window."
} else {
    Write-Host "Mode=$mode — LiveKit voice worker not required (Exotel+Gemini on API)."
}
Write-Host "Done. Run: .\scripts\test-inbound-voice.ps1"
Write-Host "Exotel applet URL: (Invoke-RestMethod http://127.0.0.1:8000/v1/ops/status).telephony.exotel_inbound_voice_url"