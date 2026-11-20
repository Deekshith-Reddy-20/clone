# Why inbound ExoPhone does not answer — checks Exotel VoiceUrl vs your ngrok webhook.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root "api\.venv\Scripts\python.exe"

if (-not (Test-Path $Py)) { throw "Missing api\.venv" }

Write-Host "=== Exotel inbound diagnosis ===" -ForegroundColor Cyan

$ops = Invoke-RestMethod "http://127.0.0.1:8000/v1/ops/status" -ErrorAction Stop
$mode = $ops.telephony.inbound_voice_mode
$want = if ($mode -eq "sarvam") { $ops.telephony.exotel_voicebot_resolve_url } else { $ops.telephony.exotel_inbound_voice_url }
$public = $ops.telephony.public_api_base_url

Write-Host "Inbound mode:              $mode"
Write-Host "Expected webhook (Karyuk): $want"
Write-Host "Public API base:          $public"
$dial = if ($ops.telephony.exotel_dial_national) { $ops.telephony.exotel_dial_national } else { $ops.telephony.exotel_caller_id }
Write-Host "Dial from mobile:         $dial"
Write-Host ""

& $Py (Join-Path $Root "scripts\exotel_incoming_status.py")
$exotelMatch = ($LASTEXITCODE -eq 0)

Write-Host ""
try {
    $h = @{ "ngrok-skip-browser-warning" = "1" }
    Invoke-RestMethod "$want" -Headers $h -Method GET -TimeoutSec 15 | Out-Null
    Write-Host "ngrok webhook: reachable (returns XML from Karyuk)" -ForegroundColor Green
} catch {
    Write-Host "ngrok webhook: NOT reachable — $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Run in a separate window: .\scripts\start-ngrok.ps1"
}

Write-Host ""
if (-not $exotelMatch) {
    Write-Host "If VoiceUrl is NOT your ngrok URL, fix Exotel (required):" -ForegroundColor Yellow
} else {
    Write-Host "Exotel VoiceUrl points at Karyuk. If calls still fail, check ngrok and API logs." -ForegroundColor Green
    exit 0
}
Write-Host "  1. my.exotel.com -> ExoPhones -> 04045900002 -> Configure incoming call"
Write-Host "  2. Create/open flow: start voice app 1385345 (or new 'Passthru' / URL flow)"
    if ($mode -eq "sarvam") {
        Write-Host "  3. Sarvam: open flow 1385345 → Voicebot applet URL = $want"
        Write-Host "     (Call Start → Voicebot only — no Hangup after it.)"
    } else {
        Write-Host "  3. Use Passthru/HTTP ExoML from: $want OR Voicebot for wss mode"
        Write-Host "     (see docs/EXOTEL_INBOUND_FLOW.md)"
    }
Write-Host "  3b. Remove Hangup right after the webhook; Karyuk XML handles the conversation."
Write-Host "  4. Save flow and assign to the ExoPhone. Call again: $dial."
Write-Host ""
Write-Host "Exotel API cannot set external VoiceUrl directly (only my.exotel.com flows)."