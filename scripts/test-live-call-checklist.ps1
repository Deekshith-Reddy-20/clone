# Pre-flight before a real Exotel test call
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "Live call pre-flight" -ForegroundColor Cyan
& (Join-Path $Root "scripts\test-ngrok.ps1")
try {
    $t = Invoke-RestMethod "http://127.0.0.1:8000/v1/ops/status"
    Write-Host "voice_runtime: $($t.voice_runtime)"
} catch {
    Write-Warning "Start API: .\serve-api.ps1"
}
Write-Host ""
Write-Host "On YOUR phone you should:"
Write-Host "  1. Ring (outbound from Exotel)"
Write-Host "  2. After answer: hear 'Connecting you to your Karyuk agent' then SIP to LiveKit"
Write-Host ""
Write-Host "For conversational AI (not just a greeting), run a LiveKit agent worker — see voice\README.md"
Write-Host ""
Write-Host "Place test call:"
Write-Host "  .\scripts\place-live-test-call.ps1 -Phone YOUR_MOBILE_10_DIGITS"