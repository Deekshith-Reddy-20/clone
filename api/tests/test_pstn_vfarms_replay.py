"""Text replay of PSTN booking path — dates frozen 2026-11-20 (mock LLM)."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.schemas.business_profile import BusinessProfile
from app.services.business_profile_render import render_profile_facts
from app.services.voice.booking_state import load_booking
from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.voice_dates import resolve_dates, today_local
from app.services.voice.voice_llm_router import LlmTurnResult

FIXTURES = Path(__file__).parent / "fixtures"
CASE = Path(__file__).parent / "conversations" / "pstn_vfarms_20261120.json"


def _mock_llm_reply(caller_text: str, fields: dict) -> str:
    st = load_booking(fields)
    r = resolve_dates(caller_text, anchor=today_local())
    if r.check_in:
        st.check_in = r.check_in
    if r.check_out:
        st.check_out = r.check_out
    fields["inbound_booking"] = fields.get("inbound_booking") or {}
    if "వస్తారు" in caller_text or "గురం" in caller_text or "four" in caller_text.lower():
        st.guest_count = 4
    if "book" in caller_text.lower() or caller_text.strip() in ("ఆ అంతే", "ఆ అంతే book చేయండి"):
        cin = st.check_in or "2026-11-22"
        g = st.guest_count or 4
        return f"సరే — {cin} check-in, {g} guests. Booking request note చేశాను, team confirm చేస్తారు."
    if st.check_in and st.guest_count:
        return f"{st.check_in} check-in, {st.guest_count} guests — confirm చేయాలా?"
    if st.check_in:
        return f"{st.check_in} check-in noted. ఎంతమంది guests?"
    return "check-in date చెప్తారా అండి?"


class PstnVfarmsReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["KARYUK_CALL_DATE"] = "2026-11-20"
        os.environ["KARYUK_VOICE_LLM_FIRST"] = "1"

    def tearDown(self) -> None:
        os.environ.pop("KARYUK_CALL_DATE", None)

    @patch("app.services.voice.inbound_llm_engine.generate_inbound_llm_turn")
    def test_replay_booking_outcome(self, mock_turn: MagicMock) -> None:
        data = json.loads(CASE.read_text(encoding="utf-8"))
        prof = json.loads((FIXTURES / data["meta"]["profile_fixture"]).read_text(encoding="utf-8"))
        facts = render_profile_facts(BusinessProfile.from_snapshot(prof))
        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
        db.add = MagicMock()

        call = MagicMock()
        call.workspace_id = "00000000-0000-0000-0000-000000000001"
        call.captured_fields = {
            "employee_brief": data["meta"]["employee_brief"],
            "employee_language": "Telugu",
            "employee_spoken_facts": facts,
            "employee_business_profile": prof,
            "employee_natural_spoken": True,
            "conversation_language": "te-IN",
            "caller_e164": "+919876543210",
            "inbound_chat": {"turns": []},
        }

        def _gen(**kwargs):
            text = (kwargs.get("caller_text") or "").split("\n")[0]
            reply = _mock_llm_reply(text, call.captured_fields or {})
            tools = []
            if "book" in text.lower() or text.strip().startswith("ఆ అంతే"):
                tools = [{"name": "create_booking", "args": {"confirmed_verbal": True}}]
            return LlmTurnResult(reply, 120.0, "sarvam", tool_calls=tools)

        mock_turn.side_effect = _gen

        flow = [
            "Checking date వచ్చేసి నేను ఎల్లుండి వద్దామనుకుంటున్నాను.",
            "4 వస్తారు.",
            "ఆ అంతే book చేయండి.",
        ]
        last = ""
        for caller in flow:
            reply, _ = process_inbound_speech(db, call, caller_text=caller, stt_language="te-IN")
            last = reply or last
            self.assertNotIn("మరోసారి చెప్పగలరా", reply or "")
            self.assertNotIn("We have covered a lot", reply or "")

        st = load_booking(call.captured_fields)
        self.assertEqual(st.check_in, data["expectations"]["check_in"])
        self.assertEqual(st.guest_count, data["expectations"]["guest_count"])
        self.assertTrue(any(w in (last or "").lower() for w in ("request", "note", "confirm")))


if __name__ == "__main__":
    unittest.main()