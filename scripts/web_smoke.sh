#!/usr/bin/env bash
# Integration smoke: Vite proxy + major workspace APIs used by the web UI.
set -euo pipefail
WEB="${WEB_BASE:-http://127.0.0.1:5173}"
CURL_WEB=(curl -sf)
if [[ "$WEB" == https://* ]]; then
  CURL_WEB+=(--insecure)
fi

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "OK: $*"; }

curl_get() {
  "${CURL_WEB[@]}" -H "Authorization: Bearer $token" "$@"
}
curl_post() {
  "${CURL_WEB[@]}" -X POST -H "Authorization: Bearer $token" -H "Content-Type: application/json" "$@"
}
curl_patch() {
  "${CURL_WEB[@]}" -X PATCH -H "Authorization: Bearer $token" -H "Content-Type: application/json" "$@"
}

[[ "$("${CURL_WEB[@]}" -o /dev/null -w "%{http_code}" "$WEB/")" == "200" ]] || fail "Vite"
curl -sf "${API_BASE:-http://127.0.0.1:8010}/health" | grep -q '"status"' || fail "API health"

token=$("${CURL_WEB[@]}" -X POST "$WEB/v1/auth/dev-session" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
me=$(curl_get "$WEB/v1/me")
ws=$(echo "$me" | python3 -c "import sys,json; print(json.load(sys.stdin)['workspaces'][0]['id'])")
p="$WEB/v1/workspaces/$ws"

emp=$(curl_post "$p/employees" -d '{"brief":"Web smoke employee","language":"English","natural_spoken":true,"mode":"instant"}')
eid=$(echo "$emp" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

curl_patch "$p/employees/$eid/draft" -d '{"brief":"Web smoke employee updated","language":"English","natural_spoken":true,"mode":"instant","revision":1}' >/dev/null
curl_post "$p/employees/$eid/publish" -d '{}' >/dev/null

RAND_PHONE=$((9000000000 + RANDOM % 99999999))
lead=$(curl_post "$p/leads" -d "{\"phone\":\"+91$RAND_PHONE\",\"name\":\"Smoke\",\"consent_source\":\"manual\"}")
lid=$(echo "$lead" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

curl_post "$p/lead-imports" -d '{"csv_text":"name,phone\nA,+9198765111111\n"}' >/dev/null
curl_post "$p/wallet/top-ups" -d '{"credits":10}' >/dev/null
curl_get "$p/wallet" >/dev/null
curl_get "$p/analytics/overview" >/dev/null
curl_get "$p/telephony/status" >/dev/null
curl_get "$p/developers/ingress" >/dev/null
curl_post "$p/webhook-endpoints" -d '{"url":"https://example.com/hook","events":["call.finalized.v1"]}' >/dev/null
curl_post "$p/integrations/calendar/connect" -d '{}' >/dev/null
camp=$(curl_post "$p/campaigns" -d "{\"name\":\"smoke\",\"employee_id\":\"$eid\",\"lead_ids\":[\"$lid\"]}")
cid=$(echo "$camp" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl_post "$p/campaigns/$cid/commands?command=start" -d '{}' >/dev/null || true
curl_post "$p/incoming-calls/simulate" -d "{\"caller_phone\":\"+919876500000\",\"employee_id\":\"$eid\"}" >/dev/null
curl_post "$p/call-requests" -H "Idempotency-Key: smoke-$RANDOM" -d "{\"lead_id\":\"$lid\",\"employee_id\":\"$eid\"}" >/dev/null || true
curl_get "$p/calls" >/dev/null
curl_patch "$p/workspace-settings" -d '{"timezone":"Asia/Kolkata","retention_days":90}' >/dev/null
curl_post "$p/knowledge/sources" -d '{"title":"smoke","content":"hello"}' >/dev/null
curl_post "$p/phone-numbers" -d "{\"e164\":\"+91$((RAND_PHONE+1))\",\"employee_id\":\"$eid\"}" >/dev/null || true
curl_post "$p/employees/$eid/voice-preview" -d '{"speaker":"shubh"}' >/dev/null

ok "all workspace routes (employee $eid)"