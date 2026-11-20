# Wire ExoPhone 04045900002 to your logged-in workspace (API).
# Usage: .\scripts\connect-exophone.ps1 -Email you@example.com -Password '...'

param(
    [string]$Email = "",
    [string]$Password = "password123",
    [string]$Base = "http://127.0.0.1:8000",
    [string]$ExoE164 = "0404590002"
)

$ErrorActionPreference = "Stop"

if (-not $Email) {
    Write-Host "Usage: .\scripts\connect-exophone.ps1 -Email YOUR_EMAIL -Password YOUR_PASSWORD"
    exit 1
}

$login = Invoke-RestMethod -Uri "$Base/v1/auth/login" -Method POST -ContentType "application/json" `
    -Body (@{ email = $Email; password = $Password } | ConvertTo-Json -Compress)
$h = @{ Authorization = "Bearer $($login.access_token)"; "Content-Type" = "application/json" }

$me = Invoke-RestMethod "$Base/v1/me" -Headers $h
$ws = $me.workspaces[0].id
$prefix = "/v1/workspaces/$ws"
$telephony = (Invoke-RestMethod "$Base/v1/ops/status").telephony

$emps = Invoke-RestMethod "$Base$prefix/employees" -Headers $h
$published = @($emps | Where-Object { $_.status -eq "published" })
if ($published.Count -eq 0) {
    Write-Error "No published employee — publish one on Team first."
}
$empId = $published[0].id

$res = Invoke-RestMethod "$Base$prefix/phone-numbers" -Method POST -Headers $h `
    -Body (@{ e164 = $ExoE164; employee_id = $empId } | ConvertTo-Json -Compress)

Write-Host "=== ExoPhone connected ===" -ForegroundColor Green
Write-Host "Number:    $ExoE164"
Write-Host "Workspace: $($me.workspaces[0].name)"
Write-Host "Employee:  $empId"
Write-Host "Phone row: $($res.id)"
Write-Host ""
Write-Host "Exotel applet URL (Passthru GET or POST):" -ForegroundColor Yellow
Write-Host "  $($telephony.exotel_inbound_voice_url)"
Write-Host ""
Write-Host "Keep running: .\serve-api.ps1 , ngrok, .\scripts\run-voice-agent.ps1"
Write-Host "Then call 0404590002 from your mobile."