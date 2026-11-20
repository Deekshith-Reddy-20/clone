"""Hospital inbound — must not enter lodging or leak brief text (reported call regression)."""

from __future__ import annotations

from tests.legacy_fastpath import skip_unless_legacy

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.voice.appointment_state import load_appointment
from app.services.voice.booking_state import load_booking
from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.inbound_vertical import inbound_vertical
from app.services.voice.spoken_output import filter_caller_facing_reply, looks_like_private_leak


class _FakeSession:
    def commit(self) -> None:
        pass

    def refresh(self, _call) -> None:
        pass


def _hospital_call() -> SimpleNamespace:
    return SimpleNamespace(
        captured_fields={
            "employee_brief": (
                "You are Ananya, AI receptionist for Karyuk Demo Hospital Hyderabad. "
                "INTERNAL: never read emergency triage steps aloud."
            ),
            "employee_language": "Telugu",
            "employee_website_knowledge": (
                "Location: Hyderabad, Gachibowli, near ORR landmark. "
                "OPD hours 9 AM to 5 PM Monday to Saturday."
            ),
            "employee_natural_spoken": True,
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
class HospitalReceptionRegression(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeSession()

    def test_vertical_is_hospital(self) -> None:
        call = _hospital_call()
        self.assertEqual(inbound_vertical(call.captured_fields), "hospital")

    def test_private_brief_filtered_from_tts(self) -> None:
        leaked = "You are Ananya, the hospital receptionist for this call."
        self.assertTrue(looks_like_private_leak(leaked))
        safe = filter_caller_facing_reply(leaked, lang="te-IN")
        self.assertNotIn("You are", safe)
        self.assertNotIn("Ananya", safe)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_reported_hospital_conversation(self, _sarvam) -> None:
        call = _hospital_call()

        def turn(q: str) -> str:
            reply, _ = process_inbound_speech(
                self.db,
                call,
                caller_text=q,
                stt_language="te-IN",
            )
            self.assertFalse(looks_like_private_leak(reply), msg=reply)
            self.assertNotIn("You are", reply)
            low = reply.lower()
            self.assertNotIn("check-in", low)
            self.assertNotIn("checkout", low)
            self.assertNotIn("చెక్-ఇన్", reply)
            self.assertNotIn("గది", reply)
            st = load_booking(call.captured_fields or {})
            self.assertFalse(st.check_in)
            self.assertFalse(st.check_out)
            return reply

        r1 = turn("హాస్పిటల్ ఎక్కడ ఉంది?")
        self.assertIn("హైదరాబాద్", r1)

        r2 = turn("doctor కలవాలి appointment కావాలి")
        self.assertTrue("అపాయింట్" in r2 or "డాక్టర్" in r2)

        turn("OPD గంటలు ఎంత varaku")
        r4 = turn("meeku checkout date enti? hotel check in")
        self.assertIn("క్షమించండి", r4)
        self.assertIn("ఓపీ", r4)

        turn("22వ తేదీ")
        r6 = turn("25వ తేదీకి మార్చండి")
        appt = load_appointment(call.captured_fields or {})
        self.assertTrue(appt.preferred_date is not None)

        r7 = turn("నా నంబర్ 6300729913")
        self.assertIn("6300729913", call.captured_fields.get("inbound_appointment", {}).get("callback_phone", ""))
        r8 = turn("మళ్ళీ నంబర్ చెప్పాలా?")
        self.assertTrue("ఉంది" in r8 or "6300729913" in r7 or "నంబర్" in r8)

        r9 = turn("బుక్ చేశారా? చూశారా?")
        self.assertTrue("కన్ఫర్మ్" in r9 or "చూస్త" in r9)
        self.assertNotIn("VF-", r9)

        r10, hang = process_inbound_speech(
            self.db,
            call,
            caller_text="అంతే చాలు, thank you",
            stt_language="te-IN",
        )
        self.assertTrue(hang)
        self.assertIn("థ్యాంక్యూ", r10)


if __name__ == "__main__":
    unittest.main()