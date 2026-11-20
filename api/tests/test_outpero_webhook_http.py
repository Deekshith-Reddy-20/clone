import hashlib
import hmac
import json
import time
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app as fastapi_app
import app.models  # noqa: F401
from app.models import Call, Lead
from app.models.identity import Workspace
from app.models.outpero import OutperoAgent
from app.routers import outpero as outpero_mod


class OutperoWebhookHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.TestingSession = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.TestingSession()
        self.ws = Workspace(id=uuid.uuid4(), name="Webhook WS")
        self.db.add(self.ws)
        self.db.flush()
        self.agent = OutperoAgent(
            workspace_id=self.ws.id,
            name="Agent",
            slug="agent-1",
            lead_secret="leadsec",
            webhook_signing_secret="whsec",
            status="active",
            schema_cache={},
            config={},
        )
        self.db.add(self.agent)
        self.db.commit()

        def _override():
            db = self.TestingSession()
            try:
                yield db
            finally:
                db.close()

        fastapi_app.dependency_overrides[get_db] = _override
        outpero_mod.SessionLocal = self.TestingSession
        self.client = TestClient(fastapi_app)

    def tearDown(self) -> None:
        fastapi_app.dependency_overrides.clear()
        self.db.close()

    def _sign(self, body: bytes) -> tuple[str, str]:
        ts = str(int(time.time()))
        dig = hmac.new(b"whsec", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        return ts, f"sha256={dig}"

    def test_rejects_bad_signature(self) -> None:
        body = b'{"event":"call.ended","call_id":"c1","to_number":"+919800011122","status":"completed"}'
        res = self.client.post(
            f"/v1/webhooks/outpero/{self.ws.id}",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Outpero-Timestamp": str(int(time.time())),
                "X-Outpero-Signature": "sha256=nope",
                "X-Outpero-Agent-Slug": "agent-1",
            },
        )
        self.assertEqual(res.status_code, 401)

    def test_accepts_valid_signature_and_processes(self) -> None:
        payload = {
            "event": "call.ended",
            "call_id": "c_http_1",
            "status": "completed",
            "duration_s": 12,
            "to_number": "+919800011122",
            "outcome": "interested",
            "summary": "Demo booked",
            "captured": {"budget": "10L"},
            "pre_call": {"lead_name": "Ravi"},
            "transcript": [{"role": "agent", "text": "Hi"}],
        }
        body = json.dumps(payload).encode()
        ts, sig = self._sign(body)
        res = self.client.post(
            f"/v1/webhooks/outpero/{self.ws.id}",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Outpero-Timestamp": ts,
                "X-Outpero-Signature": sig,
                "X-Outpero-Agent-Slug": "agent-1",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("accepted"))

        verify = self.TestingSession()
        try:
            lead = verify.execute(
                select(Lead).where(Lead.phone_e164 == "+919800011122")
            ).scalar_one_or_none()
            call = verify.execute(
                select(Call).where(Call.provider_call_sid == "c_http_1")
            ).scalar_one_or_none()
            self.assertIsNotNone(lead)
            self.assertIsNotNone(call)
            assert lead is not None and call is not None
            self.assertEqual(lead.name, "Ravi")
            self.assertEqual(call.disposition, "interested")
        finally:
            verify.close()


if __name__ == "__main__":
    unittest.main()
