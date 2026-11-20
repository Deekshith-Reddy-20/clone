# Automated inbound voice path checks (no real phone).
$ErrorActionPreference = "Stop"
$Base = if ($env:PUBLIC_API_BASE_URL) { $env:PUBLIC_API_BASE_URL.TrimEnd('/') } else { "http://127.0.0.1:8000" }
$local = "http://127.0.0.1:8000"

Write-Host "=== Inbound voice integration test ===" -ForegroundColor Cyan

$ops = Invoke-RestMethod "$local/v1/ops/status"
Write-Host "inbound_voice_mode: $($ops.telephony.inbound_voice_mode)"
Write-Host "inbound URL: $($ops.telephony.exotel_inbound_voice_url)"

$sid = "auto-test-$(Get-Random)"
$q = "From=%2B916300729913&To=04045900002&CallSid=$sid"
$xml = (Invoke-WebRequest "$local/v1/webhooks/exotel/inbound?$q" -UseBasicParsing).Content

if ($xml -notmatch '<Gather') { throw "Inbound XML missing Gather — mode may be wrong" }
Write-Host "OK: inbound returns Gather (Exotel+Gemini loop)" -ForegroundColor Green

if ($xml -match 'conversation/([a-f0-9-]{36})') {
    $callId = $Matches[1]
    $turn = Invoke-WebRequest "$local/v1/webhooks/exotel/inbound/conversation/$callId" `
        -Method POST -Body @{ SpeechResult = "I want to book a test drive tomorrow" } -UseBasicParsing
    if ($turn.Content -notmatch '<Say') { throw "Conversation turn missing Say" }
    Write-Host "OK: conversation turn returns agent speech" -ForegroundColor Green
}

if ($Base -ne $local) {
    try {
        $pub = (Invoke-WebRequest "$Base/v1/webhooks/exotel/inbound?$q" `
            -Headers @{ "ngrok-skip-browser-warning" = "1" } -UseBasicParsing).Content
        if ($pub -match '<Gather') { Write-Host "OK: public ngrok inbound" -ForegroundColor Green }
    } catch {
        Write-Warning "Public URL failed (start ngrok): $($_.Exception.Message)"
    }
}

Write-Host "ALL INBOUND CHECKS PASSED"