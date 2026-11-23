"""Acceptance tests for V-Farms stay actions (mocked authoritative API)."""

from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401
from app.models.identity import Workspace
from app.models.vfarms import VfarmsBookingAttempt, VfarmsStayQuote
from app.models import VoiceBookingRequest
from app.services.vfarms import actions


class VfarmsActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.Session()
        self.ws = Workspace(id=uuid.uuid4(), name="VF WS")
        self.other = Workspace(id=uuid.uuid4(), name="Other WS")
        self.db.add_all([self.ws, self.other])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_invalid_date_order(self) -> None:
        out = actions.check_stay_availability(
            self.db,
            workspace_id=self.ws.id,
            check_in="2026-12-10",
            check_out="2026-12-08",
            guest_count=4,
        )
        self.assertEqual(out["state"], "unknown")
        self.assertEqual(out["error"], "invalid_date_order")

    def test_ambiguous_dates(self) -> None:
        out = actions.check_stay_availability(
            self.db,
            workspace_id=self.ws.id,
            check_in="next Friday",
            check_out="Sunday",
            guest_count=4,
        )
        self.assertEqual(out["error"], "ambiguous_dates")

    @patch("app.services.vfarms.actions.vfarms_client.fetch_quote")
    @patch("app.services.vfarms.actions.vfarms_client.fetch_calendar")
    def test_unavailable_blocked_night(self, cal, quote) -> None:
        cal.return_value = {"blockedNights": ["2026-12-05"]}
        out = actions.check_stay_availability(
            self.db,
            workspace_id=self.ws.id,
            check_in="2026-12-05",
            check_out="2026-12-07",
            guest_count=10,
        )
        self.assertEqual(out["state"], "unavailable")
        quote.assert_not_called()

    @patch("app.services.vfarms.actions.vfarms_client.fetch_quote")
    @patch("app.services.vfarms.actions.vfarms_client.fetch_calendar")
    def test_quote_ready_and_workspace_isolation(self, cal, quote) -> None:
        cal.return_value = {"blockedNights": []}
        quote.return_value = {
            "available": True,
            "quote": {
                "nights": 2,
                "ratePerNight": 25000,
                "total": 56000,
                "amountDueNow": 56000,
                "currency": "INR",
            },
        }
        out = actions.check_stay_availability(
            self.db,
            workspace_id=self.ws.id,
            check_in="2026-12-05",
            check_out="2026-12-07",
            guest_count=10,
        )
        self.assertEqual(out["state"], "quote_ready")
        ref = out["quote_ref"]
        row = self.db.execute(
            select(VfarmsStayQuote).where(VfarmsStayQuote.quote_ref == ref)
        ).scalar_one()
        self.assertEqual(row.workspace_id, self.ws.id)

        # Other workspace cannot consume this quote
        bad = actions.create_stay_reservation(
            self.db,
            workspace_id=self.other.id,
            quote_ref=ref,
            caller_confirmed=True,
        )
        self.assertEqual(bad["error"], "quote_missing")

    @patch("app.services.vfarms.actions.vfarms_client.fetch_quote")
    def test_expired_quote(self, quote) -> None:
        row = VfarmsStayQuote(
            id=uuid.uuid4(),
            workspace_id=self.ws.id,
            quote_ref="vfq_expired",
            check_in="2026-12-05",
            check_out="2026-12-07",
            guest_count=10,
            currency="INR",
            total_inr=56000,
            amount_due_now_inr=56000,
            rate_per_night_inr=25000,
            nights=2,
            status="active",
            source_payload={},
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        self.db.add(row)
        self.db.commit()
        out = actions.create_stay_reservation(
            self.db,
            workspace_id=self.ws.id,
            quote_ref="vfq_expired",
            caller_confirmed=True,
        )
        self.assertEqual(out["state"], "quote_expired")
        quote.assert_not_called()

    @patch("app.services.vfarms.actions.vfarms_client.fetch_quote")
    def test_price_changed(self, quote) -> None:
        row = VfarmsStayQuote(
            id=uuid.uuid4(),
            workspace_id=self.ws.id,
            quote_ref="vfq_price",
            check_in="2026-12-05",
            check_out="2026-12-07",
            guest_count=10,
            currency="INR",
            total_inr=56000,
            amount_due_now_inr=56000,
            rate_per_night_inr=25000,
            nights=2,
            status="active",
            source_payload={},
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        self.db.add(row)
        self.db.commit()
        quote.return_value = {
            "available": True,
            "quote": {"total": 67200, "amountDueNow": 67200, "currency": "INR"},
        }
        out = actions.create_stay_reservation(
            self.db,
            workspace_id=self.ws.id,
            quote_ref="vfq_price",
            guest_name="Test Guest",
            guest_email="test@example.com",
            guest_phone="+919999999999",
            caller_confirmed=True,
        )
        self.assertEqual(out["state"], "quote_changed")
        self.assertFalse(out.get("confirmed"))

    def test_caller_declining(self) -> None:
        out = actions.create_stay_reservation(
            self.db,
            workspace_id=self.ws.id,
            quote_ref="vfq_x",
            caller_confirmed=False,
        )
        self.assertEqual(out["state"], "declined")

    def _active_quote(self, ref: str = "vfq_ok", total: int = 56000) -> VfarmsStayQuote:
        row = VfarmsStayQuote(
            id=uuid.uuid4(),
            workspace_id=self.ws.id,
            quote_ref=ref,
            check_in="2026-12-05",
            check_out="2026-12-07",
            guest_count=10,
            currency="INR",
            total_inr=total,
            amount_due_now_inr=total,
            rate_per_night_inr=25000,
            nights=2,
            status="active",
            source_payload={},
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _settings(self, *, writes: bool) -> object:
        return type(
            "S",
            (),
            {
                "vfarms_actions_enabled": True,
                "vfarms_booking_writes_enabled": writes,
                "vfarms_checkout_url": "https://vfarms.in/#book",
                "vfarms_quote_ttl_seconds": 900,
            },
        )()

    @patch("app.services.vfarms.actions.get_settings")
    @patch("app.services.vfarms.actions.vfarms_client.fetch_quote")
    def test_writes_blocked_no_false_confirm(self, quote, settings) -> None:
        settings.return_value = self._settings(writes=False)
        self._active_quote()
        quote.return_value = {
            "available": True,
            "quote": {"total": 56000, "currency": "INR"},
        }
        out = actions.create_stay_reservation(
            self.db,
            workspace_id=self.ws.id,
            quote_ref="vfq_ok",
            guest_name="Test Guest",
            guest_email="test@example.com",
            guest_phone="+919999999999",
            caller_confirmed=True,
            attempt_key="att_1",
        )
        self.assertEqual(out["state"], "writes_blocked")
        self.assertFalse(out["confirmed"])
        self.assertNotIn("Your stay is confirmed", out["speak"])
        self.assertIn("will not say the stay is booked", out["speak"].lower())
        self.assertNotIn("payment", out["speak"].lower())
        self.assertNotIn("checkout", out["speak"].lower())
        fu = self.db.execute(select(VoiceBookingRequest)).scalars().all()
        self.assertEqual(len(fu), 1)

        out2 = actions.create_stay_reservation(
            self.db,
            workspace_id=self.ws.id,
            quote_ref="vfq_ok",
            guest_name="Test Guest",
            guest_email="test@example.com",
            guest_phone="+919999999999",
            caller_confirmed=True,
            attempt_key="att_1",
        )
        self.assertEqual(out2["state"], "writes_blocked")
        attempts = self.db.execute(select(VfarmsBookingAttempt)).scalars().all()
        self.assertEqual(len(attempts), 1)

    @patch("app.services.vfarms.actions.get_settings")
    @patch("app.services.vfarms.actions.vfarms_client.fetch_quote")
    def test_missing_guest_fields(self, quote, settings) -> None:
        settings.return_value = self._settings(writes=True)
        self._active_quote("vfq_miss")
        out = actions.create_stay_reservation(
            self.db,
            workspace_id=self.ws.id,
            quote_ref="vfq_miss",
            guest_name="Only Name",
            caller_confirmed=True,
        )
        self.assertEqual(out["state"], "missing_guest_fields")
        self.assertFalse(out["confirmed"])
        quote.assert_not_called()

    @patch("app.services.vfarms.actions.get_settings")
    @patch("app.services.vfarms.actions.vfarms_client.confirm_booking")
    @patch("app.services.vfarms.actions.vfarms_client.create_hold")
    @patch("app.services.vfarms.actions.vfarms_client.fetch_quote")
    def test_confirmed_booking_with_reference_no_payment(self, quote, hold, confirm, settings) -> None:
        settings.return_value = self._settings(writes=True)
        self._active_quote("vfq_ok2")
        quote.return_value = {"available": True, "quote": {"total": 56000, "currency": "INR"}}
        hold.return_value = {
            "booking": {"id": "b1", "booking_reference": "VF-TEST-1", "total_inr": 56000}
        }
        confirm.return_value = {"status": "confirmed", "booking_reference": "VF-TEST-1"}
        out = actions.create_stay_reservation(
            self.db,
            workspace_id=self.ws.id,
            quote_ref="vfq_ok2",
            guest_name="Test Guest",
            guest_email="test@example.com",
            guest_phone="+919999999999",
            caller_confirmed=True,
            attempt_key="att_ok",
        )
        self.assertEqual(out["state"], "confirmed")
        self.assertTrue(out["confirmed"])
        self.assertEqual(out["vfarms_reference"], "VF-TEST-1")
        self.assertFalse(out.get("online_payment_required"))
        self.assertIn("VF-TEST-1", out["speak"])
        hold.assert_called_once()
        confirm.assert_called_once_with(booking_id="b1")

        # Duplicate attempt must not create a second reservation.
        hold.reset_mock()
        confirm.reset_mock()
        out2 = actions.create_stay_reservation(
            self.db,
            workspace_id=self.ws.id,
            quote_ref="vfq_ok2",
            guest_name="Test Guest",
            guest_email="test@example.com",
            guest_phone="+919999999999",
            caller_confirmed=True,
            attempt_key="att_ok",
        )
        self.assertEqual(out2["state"], "confirmed")
        hold.assert_not_called()
        confirm.assert_not_called()

    @patch("app.services.vfarms.actions.get_settings")
    @patch("app.services.vfarms.actions.vfarms_client.confirm_booking")
    @patch("app.services.vfarms.actions.vfarms_client.create_hold")
    @patch("app.services.vfarms.actions.vfarms_client.fetch_quote")
    def test_hold_without_confirm_never_says_booked(self, quote, hold, confirm, settings) -> None:
        settings.return_value = self._settings(writes=True)
        self._active_quote("vfq_hold")
        quote.return_value = {"available": True, "quote": {"total": 56000, "currency": "INR"}}
        hold.return_value = {
            "booking": {"id": "b2", "booking_reference": "VF-HOLD", "total_inr": 56000}
        }
        confirm.return_value = {"status": "held"}  # not confirmed
        out = actions.create_stay_reservation(
            self.db,
            workspace_id=self.ws.id,
            quote_ref="vfq_hold",
            guest_name="Test Guest",
            guest_email="test@example.com",
            guest_phone="+919999999999",
            caller_confirmed=True,
            attempt_key="att_hold",
        )
        self.assertEqual(out["state"], "unknown")
        self.assertFalse(out["confirmed"])
        self.assertNotIn("Your stay is confirmed", out["speak"])
        self.assertIn("will not say the stay is booked", out["speak"].lower())

    @patch("app.services.vfarms.actions.get_settings")
    @patch("app.services.vfarms.actions.vfarms_client.confirm_booking")
    @patch("app.services.vfarms.actions.vfarms_client.create_hold")
    @patch("app.services.vfarms.actions.vfarms_client.fetch_quote")
    def test_timeout_after_hold_reconciles_without_second_hold(
        self, quote, hold, confirm, settings
    ) -> None:
        from app.services.vfarms.client import VfarmsApiError

        settings.return_value = self._settings(writes=True)
        self._active_quote("vfq_to")
        quote.return_value = {"available": True, "quote": {"total": 56000, "currency": "INR"}}
        hold.return_value = {
            "booking": {"id": "b3", "booking_reference": "VF-TO", "total_inr": 56000}
        }
        confirm.side_effect = VfarmsApiError(
            "confirm_timeout", timed_out=True, may_have_succeeded=True
        )
        out = actions.create_stay_reservation(
            self.db,
            workspace_id=self.ws.id,
            quote_ref="vfq_to",
            guest_name="Test Guest",
            guest_email="test@example.com",
            guest_phone="+919999999999",
            caller_confirmed=True,
            attempt_key="att_to",
        )
        self.assertEqual(out["state"], "unknown")
        self.assertFalse(out["confirmed"])
        self.assertTrue(out.get("may_have_succeeded"))

        # Retry same attempt_key: confirm only
        hold.reset_mock()
        confirm.side_effect = None
        confirm.return_value = {"status": "confirmed", "booking_reference": "VF-TO"}
        out2 = actions.create_stay_reservation(
            self.db,
            workspace_id=self.ws.id,
            quote_ref="vfq_to",
            guest_name="Test Guest",
            guest_email="test@example.com",
            guest_phone="+919999999999",
            caller_confirmed=True,
            attempt_key="att_to",
        )
        self.assertEqual(out2["state"], "confirmed")
        hold.assert_not_called()
        confirm.assert_called_with(booking_id="b3")

    def test_staff_followup(self) -> None:
        out = actions.create_staff_followup(
            self.db,
            workspace_id=self.ws.id,
            reason="unavailable_dates",
            details={"check_in": "2026-12-15"},
        )
        self.assertEqual(out["state"], "followup_saved")
        self.assertTrue(out["followup_ref"])


if __name__ == "__main__":
    unittest.main()
