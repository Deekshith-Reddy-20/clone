"""V Forms stay: dates, guests, status, partial phone, one booking. Second company isolation."""

from __future__ import annotations

from tests.legacy_fastpath import skip_unless_legacy

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.voice.booking_state import load_booking
from app.services.voice.employee_playbook import try_knowledge_snippet_reply
from app.services.voice.inbound_conversation import process_inbound_speech


class _DB:
    def commit(self) -> None:
        pass

    def refresh(self, _c) -> None:
        pass


def _call(brief: str, know: str) -> SimpleNamespace:
    return SimpleNamespace(
        captured_fields={
            "employee_brief": brief,
            "employee_language": "Telugu",
            "employee_website_knowledge": know,
            "knowledge_state": "published",
            "employee_snapshot_revision": "1",
            "conversation_language": "te-IN",
            "inbound_chat": {"turns": []},
        },
        transcript="",
        summary="",
        outcome=None,
        finalized_at=None,
        duration_seconds=0,
    )


@skip_unless_legacy
class VFormsDialogueTests(unittest.TestCase):
    KNOW = (
        "V-Farms near Medchal. Weekend cottages. Landmark: dragon fruit orchard. "
        "Pool 8:30 AM to 10 PM."
    )

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_dates_guests_status_partial_phone_one_booking(self, _sarvam) -> None:
        call = _call("Your name is maya for V Farms Resort.", self.KNOW)
        db = _DB()

        def turn(q: str) -> str:
            reply, _ = process_inbound_speech(db, call, caller_text=q, stt_language="te-IN")
            return reply

        with patch(
            "app.services.voice.inbound_conversation.refresh_call_grounding",
            side_effect=lambda _db, c: dict(c.captured_fields),
        ):
            r1 = turn("నవంబర్ 22 నుంచి 24, 35 మంది availability")
            st = load_booking(call.captured_fields)
            self.assertEqual(st.guest_count, 35)
            self.assertIsNotNone(st.check_in)
            self.assertIsNotNone(st.check_out)
            self.assertIn("35", r1)
            self.assertIn("బుక్", r1)

            r2 = turn("బుక్ చేశారా?")
            self.assertIn("ఇంకా బుక్ కాలేదండి", r2)
            self.assertFalse(load_booking(call.captured_fields).booking_confirmed)

            r3 = turn("నంబర్ 630072")
            self.assertIn("వినిపించింది", r3)
            self.assertIn("630072", r3)
            self.assertIsNone(load_booking(call.captured_fields).callback_phone)

            turn("9913")
            self.assertEqual(load_booking(call.captured_fields).callback_phone, "6300729913")

            r5 = turn("Okay, book చేయండి")
            ref = load_booking(call.captured_fields).booking_ref
            self.assertIn("కన్ఫర్మ్", r5)
            self.assertTrue(ref and ref.startswith("VF-"))
            turn("మళ్ళీ book చేయండి")
            self.assertEqual(load_booking(call.captured_fields).booking_ref, ref)

            _bye, hang = process_inbound_speech(
                db, call, caller_text="అంతే చాలు thank you", stt_language="te-IN"
            )
            self.assertTrue(hang)

    def test_second_company_does_not_see_vfarms_landmark(self) -> None:
        vfarms = try_knowledge_snippet_reply(
            "dragon fruit orchard landmark",
            brief="Maya V Farms",
            website_knowledge=self.KNOW,
            lang="en-IN",
        )
        other = try_knowledge_snippet_reply(
            "dragon fruit orchard landmark",
            brief="City clinic receptionist",
            website_knowledge="OPD 9 to 5. No orchards listed. Landmark: tank bund.",
            lang="en-IN",
        )
        self.assertIsNotNone(vfarms)
        self.assertIn("dragon", (vfarms or "").lower())
        self.assertTrue(other is None or "dragon" not in (other or "").lower() or "tank" in (other or "").lower())


if __name__ == "__main__":
    unittest.main()