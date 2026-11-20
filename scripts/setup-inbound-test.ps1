# Register ExoPhone in workspace, publish employee, print Exotel applet URL.
param(
    [string]$Base = "http://127.0.0.1:8000",
    [string]$ExoE164 = "0404590002"
)

$ErrorActionPreference = "Stop"

function Invoke-Karyuk($Method, $Path, $Body = $null, $Token = $null) {
    $h = @{ "Content-Type" = "application/json" }
    if ($Token) { $h["Authorization"] = "Bearer $Token" }
    $json = if ($null -ne $Body) { ($Body | ConvertTo-Json -Compress) } else { $null }
    return Invoke-RestMethod -Uri "$Base$Path" -Method $Method -Headers $h -Body $json
}

$telephony = (Invoke-RestMethod "$Base/v1/ops/status").telephony
$inboundUrl = $telephony.exotel_inbound_voice_url

Write-Host "=== Inbound test setup ===" -ForegroundColor Cyan
Write-Host "Paste this URL into Exotel ExoPhone applet (Voice / Passthru GET or POST):" -ForegroundColor Yellow
Write-Host "  $inboundUrl"

$tag = Get-Random -Maximum 999999
$reg = Invoke-Karyuk POST "/v1/auth/register" @{
    name = "Inbound Tester"
    email = "inbound-$tag@example.com"
    password = "password123"
    workspace_name = "Inbound WS"
}
$token = $reg.access_token
$ws = (Invoke-Karyuk GET "/v1/me" $null $token).workspaces[0].id
$prefix = "/v1/workspaces/$ws"

$emp = Invoke-Karyuk POST "$prefix/employees" @{
    brief = "You answer inbound calls for a car dealership. Offer a test drive and capture name and preferred time."
    language = "English"
    natural_spoken = $true
    mode = "instant"
} $token
Invoke-Karyuk POST "$prefix/employees/$($emp.id)/publish" $null $token | Out-Null
Invoke-Karyuk POST "$prefix/phone-numbers" @{
    e164 = $ExoE164
    employee_id = $emp.id
} $token | Out-Null

Write-Host ""
Write-Host "Workspace routed $ExoE164 -> employee $($emp.id)" -ForegroundColor Green
Write-Host ""
Write-Host "1) ngrok: .\scripts\start-ngrok.ps1"
Write-Host "2) API:   .\serve-api.ps1"
Write-Host "3) Agent: .\scripts\run-voice-agent.ps1"
Write-Host "4) Exotel dashboard: point ExoPhone applet to the URL above"
Write-Host "5) MUST wire Exotel flow to Karyuk: .\scripts\diagnose-exotel-inbound.ps1"
Write-Host "6) Call your ExoPhone from your mobile — dial 0404590002 (same as 04045900002)."