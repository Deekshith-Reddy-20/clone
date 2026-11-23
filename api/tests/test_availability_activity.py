"""Availability activity lifecycle — no phones / secrets in serialized rows."""

from __future__ import annotations

import unittest
import uuid
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.identity import Workspace
from app.models.vfarms import VfarmsAvailabilityActivity
from app.services.vfarms import actions
from app.services.vfarms.availability_activity import (
    list_availability_activity,
    serialize_availability_activity,
)


class AvailabilityActivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.Session()
        self.ws = Workspace(id=uuid.uuid4(), name="VF Activity WS")
        self.other = Workspace(id=uuid.uuid4(), name="Other WS")
        self.db.add_all([self.ws, self.other])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_serialize_never_includes_phone_keys(self) -> None:
        row = VfarmsAvailabilityActivity(
            id=uuid.uuid4(),
            workspace_id=self.ws.id,
            state="quote_ready",
            correlation="independent",
            quote_ref="vfq_qa_test",
            check_in="2099-06-01",
            check_out="2099-06-03",
            guest_count=2,
            total_inr=1000,
            currency="INR",
        )
        self.db.add(row)
        self.db.commit()
        payload = serialize_availability_activity(row)
        blob = str(payload).lower()
        self.assertNotIn("phone", blob)
        self.assertNotIn("e164", blob)
        self.assertFalse(payload["is_reservation"])
        self.assertEqual(payload["correlation"], "independent")

    @patch("app.services.vfarms.actions.vfarms_client.fetch_quote")
    @patch("app.services.vfarms.actions.vfarms_client.fetch_calendar")
    def test_check_stay_records_independent_activity(self, cal, quote) -> None:
        cin = (date.today() + timedelta(days=120)).isoformat()
        cout = (date.today() + timedelta(days=122)).isoformat()
        cal.return_value = {"blockedNights": []}
        quote.return_value = {
            "available": True,
            "quote": {
                "total": 42000,
                "amountDueNow": 42000,
                "nights": 2,
                "ratePerNight": 21000,
                "currency": "INR",
            },
        }
        result = actions.check_stay_availability(
            self.db,
            workspace_id=self.ws.id,
            check_in=cin,
            check_out=cout,
            guest_count=2,
        )
        self.assertEqual(result["state"], "quote_ready")
        self.assertEqual(result["availability_correlation"], "independent")
        self.assertTrue(result.get("availability_activity_id"))

        items = list_availability_activity(self.db, workspace_id=self.ws.id, limit=10)
        matched = next(i for i in items if i["id"] == result["availability_activity_id"])
        self.assertEqual(matched["state"], "quote_ready")
        self.assertEqual(matched["correlation"], "independent")
        self.assertFalse(matched["in_flight"])

        other_items = list_availability_activity(self.db, workspace_id=self.other.id, limit=10)
        self.assertEqual(other_items, [])

    @patch("app.services.vfarms.actions.vfarms_client.fetch_quote")
    @patch("app.services.vfarms.actions.vfarms_client.fetch_calendar")
    def test_link_attempted_not_found(self, cal, quote) -> None:
        cin = (date.today() + timedelta(days=130)).isoformat()
        cout = (date.today() + timedelta(days=132)).isoformat()
        cal.return_value = {"blockedNights": []}
        quote.return_value = {
            "available": True,
            "quote": {
                "total": 1000,
                "amountDueNow": 1000,
                "nights": 2,
                "ratePerNight": 500,
                "currency": "INR",
            },
        }
        result = actions.check_stay_availability(
            self.db,
            workspace_id=self.ws.id,
            check_in=cin,
            check_out=cout,
            guest_count=2,
            provider_call_id="qa-live-inbound-missing-call",
        )
        self.assertEqual(result["availability_correlation"], "link_attempted_not_found")
        self.assertFalse(result.get("quote_associated"))

        row = self.db.scalars(
            select(VfarmsAvailabilityActivity).where(
                VfarmsAvailabilityActivity.id == uuid.UUID(result["availability_activity_id"])
            )
        ).one()
        self.assertEqual(row.provider_call_id, "qa-live-inbound-missing-call")
        self.assertIsNone(row.associated_call_id)

    def test_list_excludes_isolated_qa_provider_call_ids(self) -> None:
        from app.services.vfarms.availability_activity import begin_availability_activity

        visible = begin_availability_activity(
            self.db,
            workspace_id=self.ws.id,
            provider_call_id=None,
            check_in="2027-08-01",
            check_out="2027-08-03",
            guest_count=2,
        )
        qa = begin_availability_activity(
            self.db,
            workspace_id=self.ws.id,
            provider_call_id="qa-live-inbound-filter-check",
            check_in="2027-08-10",
            check_out="2027-08-12",
            guest_count=2,
        )
        ordinary = list_availability_activity(self.db, workspace_id=self.ws.id, limit=10)
        ids = {item["id"] for item in ordinary}
        self.assertIn(str(visible.id), ids)
        self.assertNotIn(str(qa.id), ids)
        with_qa = list_availability_activity(
            self.db, workspace_id=self.ws.id, limit=10, include_isolated_qa=True
        )
        self.assertIn(str(qa.id), {item["id"] for item in with_qa})

    @patch("app.services.vfarms.actions.vfarms_client.fetch_calendar")
    def test_lookup_failed_records_activity(self, cal) -> None:
        from app.services.vfarms.client import VfarmsApiError

        cin = (date.today() + timedelta(days=140)).isoformat()
        cout = (date.today() + timedelta(days=142)).isoformat()
        cal.side_effect = VfarmsApiError("calendar down")
        result = actions.check_stay_availability(
            self.db,
            workspace_id=self.ws.id,
            check_in=cin,
            check_out=cout,
            guest_count=2,
        )
        self.assertEqual(result["error"], "calendar_error")
        self.assertTrue(result.get("availability_activity_id"))
        row = self.db.get(VfarmsAvailabilityActivity, uuid.UUID(result["availability_activity_id"]))
        self.assertEqual(row.state, "lookup_failed")
        self.assertEqual(row.error_code, "calendar_error")


if __name__ == "__main__":
    unittest.main()
