"""In-process smoke test (SQLite) when Postgres/Docker is unavailable."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
DB_PATH = API / "data" / "smoke.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ.setdefault("DEV_AUTH_ENABLED", "true")
os.environ.setdefault("JWT_SECRET", "smoke-test-secret")
os.environ.setdefault("JWT_ISSUER", "karyuk-dev")
os.environ.setdefault("JWT_AUDIENCE", "karyuk-api")

sys.path.insert(0, str(API))

from app.config import get_settings

get_settings.cache_clear()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database
from app.database import Base
import app.models  # noqa: F401

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
database.engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
database.SessionLocal = sessionmaker(bind=database.engine, autoflush=False, autocommit=False)

if database.engine.dialect.name == "sqlite":
    Base.metadata.drop_all(bind=database.engine)
Base.metadata.create_all(bind=database.engine)

from fastapi.testclient import TestClient
from app.main import app


def main() -> int:
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200 and health.json()["status"] == "ok"

    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/v1/auth/register",
        json={
            "name": "Smoke Test",
            "email": email,
            "password": "password123",
            "workspace_name": "Smoke WS",
        },
    )
    assert reg.status_code == 200, reg.text
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = client.get("/v1/me", headers=headers)
    assert me.status_code == 200
    ws = me.json()["workspaces"][0]["id"]
    prefix = f"/v1/workspaces/{ws}"

    emp = client.post(
        f"{prefix}/employees",
        headers=headers,
        json={
            "brief": "Call leads and book appointments for smoke test run",
            "language": "English",
            "natural_spoken": True,
            "mode": "instant",
        },
    )
    assert emp.status_code == 201, emp.text
    emp_id = emp.json()["id"]

    pub = client.post(f"{prefix}/employees/{emp_id}/publish", headers=headers)
    assert pub.status_code == 201, pub.text

    lead = client.post(
        f"{prefix}/leads",
        headers=headers,
        json={"phone": "9876543210", "name": "Lead"},
    )
    assert lead.status_code == 201, lead.text

    call = client.post(
        f"{prefix}/call-requests",
        headers={**headers, "Idempotency-Key": f"smoke-{lead.json()['id']}"},
        json={"lead_id": lead.json()["id"], "employee_id": emp_id},
    )
    assert call.status_code == 202, call.text
    assert call.json().get("call_id"), call.json()

    analytics = client.get(f"{prefix}/analytics/overview", headers=headers)
    assert analytics.status_code == 200
    assert analytics.json()["attempted"] >= 1

    wallet = client.get(f"{prefix}/wallet", headers=headers)
    assert wallet.status_code == 200

    print("SMOKE OK", {"workspace": ws, "employee": emp_id, "call": call.json()["call_id"]})
    print(f"(sqlite: {DB_PATH})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("SMOKE FAILED:", exc)
        raise SystemExit(1) from exc