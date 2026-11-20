"""HTTP smoke against a running API on :8000 (Postgres migrated).

All-in-one (from repo root kar-yuk\\):
  .\\scripts\\run_smoke_e2e.ps1

Manual — venv lives in api\\.venv (NOT repo root .venv):

  # terminal 1 — repo root
  docker compose up db -d
  cd api
  .\\migrate.ps1
  .\\serve.ps1

  # terminal 2 — repo root (not inside api\\)
  .\\api\\.venv\\Scripts\\python.exe .\\scripts\\smoke_e2e.py

From api\\ folder, use .\\.venv\\... not ..\\.venv or api\\.venv
(PowerShell treats bare api\\ as a module name when cwd is already api\\).
"""

import json
import os
import sys
import urllib.error
import urllib.request

# Default :8000 for manual runs; run_smoke_e2e.ps1 uses :8001 to avoid clashing with dev --reload on :8000.
BASE = os.environ.get("SMOKE_E2E_BASE", "http://127.0.0.1:8000").rstrip("/")


def req(method: str, path: str, data: dict | None = None, token: str | None = None, headers: dict | None = None):
    body = None if data is None else json.dumps(data).encode()
    h = {"Content-Type": "application/json", **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print("FAIL", path, e.code, e.read().decode())
        raise


def main() -> int:
    health = req("GET", "/health")
    assert health.get("status") == "ok"
    reg = req(
        "POST",
        "/v1/auth/register",
        {
            "name": "Smoke Test",
            "email": f"smoke-{__import__('uuid').uuid4().hex[:8]}@example.com",
            "password": "password123",
            "workspace_name": "Smoke WS",
        },
    )
    token = reg["access_token"]
    me = req("GET", "/v1/me", token=token)
    ws = me["workspaces"][0]["id"]
    prefix = f"/v1/workspaces/{ws}"

    emp = req(
        "POST",
        f"{prefix}/employees",
        {
            "brief": "Call leads and book appointments for smoke test",
            "language": "English",
            "natural_spoken": True,
            "mode": "instant",
        },
        token=token,
    )
    req("POST", f"{prefix}/employees/{emp['id']}/publish", token=token)

    lead = req("POST", f"{prefix}/leads", {"phone": "9876543210", "name": "Lead"}, token=token)
    call = req(
        "POST",
        f"{prefix}/call-requests",
        {"lead_id": lead["id"], "employee_id": emp["id"]},
        token=token,
        headers={"Idempotency-Key": f"smoke-{lead['id']}"},
    )
    assert call.get("call_id"), call

    analytics = req("GET", f"{prefix}/analytics/overview", token=token)
    assert analytics["attempted"] >= 1

    print("SMOKE OK", {"workspace": ws, "employee": emp["id"], "call": call["call_id"]})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("SMOKE FAILED:", exc)
        raise SystemExit(1) from exc