# Place a real Exotel test call via API and poll status until terminal.
# Usage:
#   .\scripts\place-live-test-call.ps1 -Phone 9876543210
#   .\scripts\place-live-test-call.ps1 -Phone 9876543210 -EmployeeId <uuid>

param(
    [Parameter(Mandatory = $true)]
    [string]$Phone,
    [string]$EmployeeId = "",
    [string]$Base = "http://127.0.0.1:8000",
    [string]$Name = "Live test"
)

$ErrorActionPreference = "Stop"

function Invoke-Karyuk($Method, $Path, $Body = $null, $Token = $null) {
    $h = @{ "Content-Type" = "application/json" }
    if ($Token) { $h["Authorization"] = "Bearer $Token" }
    $json = if ($null -ne $Body) { ($Body | ConvertTo-Json -Compress) } else { $null }
    return Invoke-RestMethod -Uri "$Base$Path" -Method $Method -Headers $h -Body $json
}

Write-Host "=== Karyuk live call test ===" -ForegroundColor Cyan
Write-Host "API: $Base"

try {
    $telephony = (Invoke-RestMethod "$Base/v1/ops/status").telephony
} catch {
    Write-Error "API not reachable. Run .\serve-api.ps1"
}
if (-not $telephony.exotel_configured) {
    Write-Error "Exotel not configured in .env"
}
Write-Host "Telephony: $($telephony.mode) | public: $($telephony.public_api_base_url)"

$tag = Get-Random -Maximum 999999
$email = "live-test-$tag@example.com"
$reg = Invoke-Karyuk POST "/v1/auth/register" @{
    name = "Live Tester"
    email = $email
    password = "password123"
    workspace_name = "Live Test WS"
}
$token = $reg.access_token
$me = Invoke-Karyuk GET "/v1/me" $null $token
$ws = $me.workspaces[0].id
$prefix = "/v1/workspaces/$ws"

if (-not $EmployeeId) {
    $emp = Invoke-Karyuk POST "$prefix/employees" @{
        brief = "Answer the call, confirm test drive booking, and be polite in English."
        language = "English"
        natural_spoken = $true
        mode = "instant"
    } $token
    $EmployeeId = $emp.id
    Write-Host "Created employee $EmployeeId"
}
try {
    Invoke-Karyuk POST "$prefix/employees/$EmployeeId/publish" $null $token | Out-Null
    Write-Host "Published employee."
} catch {
    Write-Host "Publish (may already be published): $($_.Exception.Message)"
}

$res = Invoke-Karyuk POST "$prefix/employees/$EmployeeId/test-calls" @{ phone = $Phone; name = $Name } $token
$callId = $res.call_id
Write-Host "Test call started: $callId"
Write-Host "  provider: $($res.provider) outcome: $($res.outcome) livekit: $($res.livekit_room)"

$terminal = @("completed", "failed", "busy", "no_answer", "canceled")
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 2
    if ($res.provider -eq "exotel") {
        try {
            Invoke-Karyuk POST "$prefix/calls/$callId/sync-provider" $null $token | Out-Null
        } catch {}
    }
    $detail = Invoke-Karyuk GET "$prefix/calls/$callId" $null $token
    $outcome = $detail.outcome
    Write-Host "  [$i] outcome=$outcome realtime=$($detail.realtime)"
    if ($terminal -contains $outcome) {
        Write-Host ""
        Write-Host "FINAL: $outcome (duration $($detail.duration_seconds)s, provider $($detail.provider))"
        if ($detail.summary) { Write-Host "Summary: $($detail.summary)" }
        if ($outcome -eq "completed") {
            Write-Host "SUCCESS: Call completed. Check your phone and Exotel dashboard." -ForegroundColor Green
        } elseif ($outcome -in @("no_answer", "busy", "failed")) {
            Write-Host "Call did not connect — check number, Exotel balance, and caller ID." -ForegroundColor Yellow
        }
        exit 0
    }
}
Write-Host "Timed out waiting for terminal status — check Exotel dashboard and ngrok logs."
exit 1