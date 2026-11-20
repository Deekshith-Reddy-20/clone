import unittest
import uuid
from unittest.mock import MagicMock

from app.models.enums import CallOutcome
from app.services.outpero.sync import (
    build_event_key,
    derive_qualification,
    extract_phone,
    format_transcript,
    map_outpero_status_to_outcome,
    upsert_call_from_outpero,
    upsert_lead_from_outpero,
)


class OutperoSyncUnitTests(unittest.TestCase):
    def test_format_transcript_list(self) -> None:
        text = format_transcript(
            [
                {"role": "agent", "text": "Hello"},
                {"role": "caller", "text": "Hi"},
            ]
        )
        self.assertIn("agent: Hello", text or "")
        self.assertIn("caller: Hi", text or "")

    def test_map_outcomes(self) -> None:
        self.assertEqual(map_outpero_status_to_outcome("completed"), CallOutcome.completed)
        self.assertEqual(map_outpero_status_to_outcome("voicemail"), CallOutcome.completed)
        self.assertEqual(map_outpero_status_to_outcome("busy"), CallOutcome.busy)

    def test_qualification(self) -> None:
        self.assertEqual(derive_qualification("interested", {}), "interested")
        self.assertEqual(derive_qualification("callback", {}), "follow_up_required")

    def test_event_key_stable(self) -> None:
        payload = {"event": "call.ended", "call_id": "c_abc", "ended_at": "t1"}
        self.assertEqual(build_event_key(payload), "call.ended:c_abc:t1")

    def test_extract_phone(self) -> None:
        self.assertEqual(extract_phone({"to_number": "+919876543210"}), "+919876543210")
        self.assertEqual(extract_phone({"to_number": "9876543210"}), "+919876543210")


class OutperoUpsertTests(unittest.TestCase):
    def test_upsert_lead_and_call_idempotent(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.database import Base
        import app.models  # noqa: F401 — register metadata
        from app.models.identity import Workspace
        from app.models.outpero import OutperoAgent

        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        ws = Workspace(id=uuid.uuid4(), name="Test WS")
        db.add(ws)
        db.flush()
        agent = OutperoAgent(
            workspace_id=ws.id,
            name="Meera",
            slug="meera",
            lead_secret="secret",
            status="active",
            schema_cache={},
            config={},
        )
        db.add(agent)
        db.commit()

        payload = {
            "event": "call.ended",
            "call_id": "c_dup_1",
            "status": "completed",
            "duration_s": 40,
            "to_number": "+919811122233",
            "outcome": "interested",
            "summary": "Wants a demo",
            "captured": {"budget": "50L", "email": "a@example.com"},
            "pre_call": {"lead_name": "Anita"},
            "transcript": [{"role": "agent", "text": "Hi"}, {"role": "caller", "text": "Hello"}],
            "recording_url": "https://example.com/r.mp3",
        }

        lead1 = upsert_lead_from_outpero(db, workspace_id=ws.id, payload=payload, agent=agent)
        call1 = upsert_call_from_outpero(
            db, workspace_id=ws.id, payload=payload, agent=agent, lead=lead1
        )
        db.commit()

        # Second delivery should update same rows, not duplicate
        payload2 = {**payload, "summary": "Wants a demo Saturday", "duration_s": 55}
        lead2 = upsert_lead_from_outpero(db, workspace_id=ws.id, payload=payload2, agent=agent)
        call2 = upsert_call_from_outpero(
            db, workspace_id=ws.id, payload=payload2, agent=agent, lead=lead2
        )
        db.commit()

        self.assertEqual(lead1.id, lead2.id)
        self.assertEqual(call1.id, call2.id)
        self.assertEqual(lead2.name, "Anita")
        self.assertEqual(lead2.email, "a@example.com")
        self.assertEqual(lead2.budget, "50L")
        self.assertEqual(call2.summary, "Wants a demo Saturday")
        self.assertEqual(call2.duration_seconds, 55)
        self.assertEqual(call2.provider_call_sid, "c_dup_1")

        # Preserve budget when omitted
        payload3 = {
            **payload,
            "captured": {"email": "a@example.com"},
            "summary": "Follow-up",
        }
        lead3 = upsert_lead_from_outpero(db, workspace_id=ws.id, payload=payload3, agent=agent)
        self.assertEqual(lead3.budget, "50L")


if __name__ == "__main__":
    unittest.main()
