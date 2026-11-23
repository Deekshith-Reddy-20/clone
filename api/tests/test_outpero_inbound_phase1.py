"""Phase-1 Outpero inbound call import tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app as fastapi_app
import app.models  # noqa: F401
from app.models import Call
from app.models.identity import Workspace
from app.models.outpero import OutperoAgent, OutperoInboundConnection, OutperoWebhookEvent
from app.routers import outpero as outpero_mod
from app.services.outpero.inbound_import import process_inbound_call_ended
from app.services.outpero.signatures import verify_outpero_signature


def _sign(secret: str, body: bytes, ts: str | None = None) -> tuple[str, str]:
    ts = ts or str(int(time.time()))
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return ts, f"sha256={digest}"


class OutperoInboundPhase1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.Session()

        self.ws = Workspace(id=uuid.uuid4(), name="Staging WS")
        self.db.add(self.ws)
        self.agent = OutperoAgent(
            id=uuid.uuid4(),
            workspace_id=self.ws.id,
            name="Harish",
            slug="harish-slug",
            lead_secret="lead-secret",
            webhook_signing_secret=None,
            status="active",
        )
        self.db.add(self.agent)
        self.secret = "whsec_inbound_test"
        self.connection = OutperoInboundConnection(
            id=uuid.uuid4(),
            connection_key="harish-staging",
            workspace_id=self.ws.id,
            outpero_agent_id=self.agent.id,
            employee_slug="harish-slug",
            did_e164="+919876543210",
            signing_secret=self.secret,
            enabled=True,
            phase="inbound_call_import_v1",
        )
        self.db.add(self.connection)
        self.db.commit()

        def _override():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        fastapi_app.dependency_overrides[get_db] = _override
        outpero_mod.SessionLocal = self.Session
        self.client = TestClient(fastapi_app)

        self._settings_patch = patch(
            "app.routers.outpero.get_settings",
            return_value=type(
                "S",
                (),
                {
                    "outpero_inbound_import_enabled": True,
                    "outpero_inbound_webhook_secret": "",
                    "outpero_webhook_shared_secret": "",
                    "outpero_webhook_max_age_seconds": 300,
                    "outpero_inbound_accept_unsigned": False,
                    "karyuk_deployment": "staging",
                    "app_env": "staging",
                },
            )(),
        )
        self._settings_patch.start()
        self._enabled_patch = patch(
            "app.routers.outpero.inbound_import_enabled", return_value=True
        )
        self._enabled_patch.start()

    def tearDown(self) -> None:
        self._settings_patch.stop()
        self._enabled_patch.stop()
        fastapi_app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def _payload(self, call_id: str = "c_phase1_1", **extra) -> dict:
        body = {
            "event": "call.ended",
            "call_id": call_id,
            "status": "completed",
            "direction": "inbound",
            "employee": "harish-slug",
            "from_number": "+911112223333",
            "to_number": "+919876543210",
            "duration_s": 42,
            "started_at": "2026-11-21T10:00:00Z",
            "ended_at": "2026-11-21T10:00:42Z",
            "transcript": [{"role": "assistant", "content": "Hello from Asha"}],
            "summary": "Caller asked about December availability.",
            "recording_url": "https://example.invalid/rec",
            "captured": {"budget": "SHOULD_NOT_STORE_IN_CAPTURED"},
        }
        body.update(extra)
        return body

    def test_valid_signing_imports_transcript_not_captured_blob(self) -> None:
        payload = self._payload()
        raw = json.dumps(payload, separators=(",", ":")).encode()
        ts, sig = _sign(self.secret, raw)
        res = self.client.post(
            "/v1/webhooks/outpero/inbound/harish-staging",
            content=raw,
            headers={
                "content-type": "application/json",
                "X-Outpero-Timestamp": ts,
                "X-Outpero-Signature": sig,
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["accepted"])

        # Background task runs inside TestClient
        db = self.Session()
        call = db.execute(
            select(Call).where(Call.provider_call_sid == "c_phase1_1")
        ).scalar_one()
        self.assertEqual(call.workspace_id, self.ws.id)
        self.assertIn("assistant: Hello from Asha", call.transcript or "")
        self.assertEqual(call.summary, "Caller asked about December availability.")
        self.assertIsNone(call.recording_url)
        self.assertIsNone(call.lead_id)
        self.assertFalse((call.captured_fields or {}).get("transcript_excluded"))
        self.assertNotIn("budget", str(call.captured_fields))
        db.close()

    def test_empty_transcript_replay_does_not_wipe(self) -> None:
        from app.services.outpero.inbound_import import upsert_inbound_call_metadata

        first = self._payload(call_id="c_phase1_keep")
        call = upsert_inbound_call_metadata(
            self.db,
            workspace_id=self.ws.id,
            payload=first,
            connection=self.connection,
        )
        self.db.commit()
        self.assertTrue(call.transcript)
        kept = call.transcript

        empty_replay = {k: v for k, v in first.items() if k not in {"transcript", "summary"}}
        empty_replay["transcript"] = []
        empty_replay["summary"] = ""
        call2 = upsert_inbound_call_metadata(
            self.db,
            workspace_id=self.ws.id,
            payload=empty_replay,
            connection=self.connection,
        )
        self.db.commit()
        self.assertEqual(call2.id, call.id)
        self.assertEqual(call2.transcript, kept)
        self.assertEqual(call2.summary, "Caller asked about December availability.")
        # Empty replay must not wipe caller/route legs either.
        self.assertEqual((call2.captured_fields or {}).get("from_number"), "+911112223333")
        self.assertEqual((call2.captured_fields or {}).get("to_number"), "+919876543210")

        omitted_legs = {
            k: v for k, v in first.items() if k not in {"transcript", "summary", "from_number", "to_number"}
        }
        omitted_legs["transcript"] = []
        omitted_legs["summary"] = ""
        omitted_legs["to_number"] = "+919876543210"
        call3 = upsert_inbound_call_metadata(
            self.db,
            workspace_id=self.ws.id,
            payload=omitted_legs,
            connection=self.connection,
        )
        self.db.commit()
        self.assertEqual((call3.captured_fields or {}).get("from_number"), "+911112223333")

    def test_swapped_did_on_from_stores_customer_as_caller(self) -> None:
        from app.services.outpero.inbound_import import upsert_inbound_call_metadata

        payload = self._payload(
            call_id="c_phase1_swap",
            from_number="+919876543210",  # DID (route)
            to_number="+917075398906",  # remote party
            customer_number="+917075398906",
            business_number="+919876543210",
        )
        call = upsert_inbound_call_metadata(
            self.db,
            workspace_id=self.ws.id,
            payload=payload,
            connection=self.connection,
        )
        self.db.commit()
        self.assertEqual((call.captured_fields or {}).get("from_number"), "+917075398906")
        self.assertEqual((call.captured_fields or {}).get("to_number"), "+919876543210")

    def test_invalid_signature_rejected(self) -> None:
        raw = json.dumps(self._payload()).encode()
        ts, _ = _sign(self.secret, raw)
        res = self.client.post(
            "/v1/webhooks/outpero/inbound/harish-staging",
            content=raw,
            headers={
                "content-type": "application/json",
                "X-Outpero-Timestamp": ts,
                "X-Outpero-Signature": "sha256=deadbeef",
            },
        )
        self.assertEqual(res.status_code, 401)

    def test_modified_body_rejected(self) -> None:
        payload = self._payload()
        raw = json.dumps(payload, separators=(",", ":")).encode()
        ts, sig = _sign(self.secret, raw)
        tampered = json.dumps({**payload, "duration_s": 99}, separators=(",", ":")).encode()
        res = self.client.post(
            "/v1/webhooks/outpero/inbound/harish-staging",
            content=tampered,
            headers={
                "content-type": "application/json",
                "X-Outpero-Timestamp": ts,
                "X-Outpero-Signature": sig,
            },
        )
        self.assertEqual(res.status_code, 401)

    def test_stale_timestamp_rejected(self) -> None:
        raw = json.dumps(self._payload()).encode()
        ts = str(int(time.time()) - 10_000)
        _, sig = _sign(self.secret, raw, ts=ts)
        res = self.client.post(
            "/v1/webhooks/outpero/inbound/harish-staging",
            content=raw,
            headers={
                "content-type": "application/json",
                "X-Outpero-Timestamp": ts,
                "X-Outpero-Signature": sig,
            },
        )
        self.assertEqual(res.status_code, 401)

    def test_millisecond_timestamp_accepted(self) -> None:
        body = b'{"event":"call.ended"}'
        ts_ms = str(int(time.time() * 1000))
        digest = hmac.new(self.secret.encode(), f"{ts_ms}.".encode() + body, hashlib.sha256).hexdigest()
        self.assertTrue(
            verify_outpero_signature(
                secret=self.secret,
                timestamp=ts_ms,
                signature_header=f"sha256={digest}",
                raw_body=body,
            )
        )

    def test_disabled_connection_rejected(self) -> None:
        self.connection.enabled = False
        self.db.commit()
        raw = json.dumps(self._payload()).encode()
        ts, sig = _sign(self.secret, raw)
        res = self.client.post(
            "/v1/webhooks/outpero/inbound/harish-staging",
            content=raw,
            headers={
                "content-type": "application/json",
                "X-Outpero-Timestamp": ts,
                "X-Outpero-Signature": sig,
            },
        )
        self.assertEqual(res.status_code, 404)

    def test_employee_mismatch_rejected(self) -> None:
        raw = json.dumps(self._payload(employee="ZzOtherSlug9NotHarishXX")).encode()
        ts, sig = _sign(self.secret, raw)
        res = self.client.post(
            "/v1/webhooks/outpero/inbound/harish-staging",
            content=raw,
            headers={
                "content-type": "application/json",
                "X-Outpero-Timestamp": ts,
                "X-Outpero-Signature": sig,
            },
        )
        self.assertEqual(res.status_code, 403)

    def test_did_mismatch_rejected(self) -> None:
        raw = json.dumps(
            self._payload(to_number="+911111111111", from_number="+911111111112")
        ).encode()
        ts, sig = _sign(self.secret, raw)
        res = self.client.post(
            "/v1/webhooks/outpero/inbound/harish-staging",
            content=raw,
            headers={
                "content-type": "application/json",
                "X-Outpero-Timestamp": ts,
                "X-Outpero-Signature": sig,
            },
        )
        self.assertEqual(res.status_code, 403)

    def test_inbound_did_on_from_number_accepted(self) -> None:
        """Live Outpero may put the bound DID on from_number and the remote on to_number."""
        raw = json.dumps(
            self._payload(
                call_id="c_did_from_leg",
                to_number="+917075398906",
                from_number="+919876543210",
            )
        ).encode()
        ts, sig = _sign(self.secret, raw)
        res = self.client.post(
            "/v1/webhooks/outpero/inbound/harish-staging",
            content=raw,
            headers={
                "content-type": "application/json",
                "X-Outpero-Timestamp": ts,
                "X-Outpero-Signature": sig,
            },
        )
        self.assertEqual(res.status_code, 200)
        db = self.Session()
        row = db.execute(select(Call).where(Call.provider_call_sid == "c_did_from_leg")).scalar_one()
        self.assertEqual(row.provider, "outpero")
        db.close()

    def test_duplicate_delivery_no_second_call(self) -> None:
        payload = self._payload(call_id="c_dup")
        raw = json.dumps(payload, separators=(",", ":")).encode()
        ts, sig = _sign(self.secret, raw)
        headers = {
            "content-type": "application/json",
            "X-Outpero-Timestamp": ts,
            "X-Outpero-Signature": sig,
        }
        r1 = self.client.post("/v1/webhooks/outpero/inbound/harish-staging", content=raw, headers=headers)
        r2 = self.client.post("/v1/webhooks/outpero/inbound/harish-staging", content=raw, headers=headers)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get("duplicate") or r2.json().get("accepted"))
        db = self.Session()
        count = len(
            db.execute(select(Call).where(Call.provider_call_sid == "c_dup")).scalars().all()
        )
        self.assertEqual(count, 1)
        db.close()

    def test_concurrent_duplicates(self) -> None:
        # Sequential rapid redelivery — SQLite StaticPool is not safe for threaded writes.
        payload = self._payload(call_id="c_race")
        raw = json.dumps(payload, separators=(",", ":")).encode()
        results = []
        for _ in range(4):
            ts, sig = _sign(self.secret, raw)
            results.append(
                self.client.post(
                    "/v1/webhooks/outpero/inbound/harish-staging",
                    content=raw,
                    headers={
                        "content-type": "application/json",
                        "X-Outpero-Timestamp": ts,
                        "X-Outpero-Signature": sig,
                    },
                )
            )
        self.assertTrue(all(r.status_code == 200 for r in results))
        db = self.Session()
        events = (
            db.execute(
                select(OutperoWebhookEvent).where(
                    OutperoWebhookEvent.event_key == "inbound:harish-staging:c_race"
                )
            )
            .scalars()
            .all()
        )
        self.assertEqual(len(events), 1)
        calls = (
            db.execute(select(Call).where(Call.provider_call_sid == "c_race")).scalars().all()
        )
        self.assertEqual(len(calls), 1)
        db.close()

    def test_recovery_after_processing_failure(self) -> None:
        payload = self._payload(call_id="c_fail_then_ok")
        event = OutperoWebhookEvent(
            id=uuid.uuid4(),
            workspace_id=self.ws.id,
            outpero_agent_id=self.agent.id,
            event_key="inbound:harish-staging:c_fail_then_ok",
            external_call_id="c_fail_then_ok",
            event_type="call.ended",
            payload=payload,
            status="failed",
            error_message="boom",
        )
        self.db.add(event)
        self.db.commit()

        process_inbound_call_ended(
            self.db,
            connection=self.connection,
            payload=payload,
            event_row=event,
            is_test=True,
        )
        self.db.refresh(event)
        self.assertEqual(event.status, "processed")
        call = self.db.execute(
            select(Call).where(Call.provider_call_sid == "c_fail_then_ok")
        ).scalar_one()
        self.assertEqual(call.workspace_id, self.ws.id)

    def test_cross_workspace_isolation(self) -> None:
        other = Workspace(id=uuid.uuid4(), name="Other")
        self.db.add(other)
        self.db.commit()
        payload = self._payload(call_id="c_iso")
        process_inbound_call_ended(
            self.db,
            connection=self.connection,
            payload=payload,
            event_row=None,
            is_test=True,
        )
        call = self.db.execute(
            select(Call).where(Call.provider_call_sid == "c_iso")
        ).scalar_one()
        self.assertEqual(call.workspace_id, self.ws.id)
        self.assertNotEqual(call.workspace_id, other.id)
        foreign = self.db.execute(
            select(Call).where(
                Call.workspace_id == other.id, Call.provider_call_sid == "c_iso"
            )
        ).scalar_one_or_none()
        self.assertIsNone(foreign)

    def test_feature_flag_off_returns_503(self) -> None:
        self._enabled_patch.stop()
        with patch("app.routers.outpero.inbound_import_enabled", return_value=False):
            raw = json.dumps(self._payload()).encode()
            ts, sig = _sign(self.secret, raw)
            res = self.client.post(
                "/v1/webhooks/outpero/inbound/harish-staging",
                content=raw,
                headers={
                    "content-type": "application/json",
                    "X-Outpero-Timestamp": ts,
                    "X-Outpero-Signature": sig,
                },
            )
            self.assertEqual(res.status_code, 503)
        self._enabled_patch = patch(
            "app.routers.outpero.inbound_import_enabled", return_value=True
        )
        self._enabled_patch.start()


if __name__ == "__main__":
    unittest.main()
