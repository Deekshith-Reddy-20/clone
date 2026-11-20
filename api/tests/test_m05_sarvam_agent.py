"""karyuk-m05 phone agent answers through Sarvam chat, not Gemini."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.m05_sarvam import (
    employee_lang_code,
    m05_voice_enabled,
    phone_instructions,
    spoken_opening,
)


class _FakeSession:
    def commit(self) -> None:
        pass

    def refresh(self, _call) -> None:
        pass


class M05SarvamAgent(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = os.environ.get("KARYUK_VOICE_AGENT")
        os.environ["KARYUK_VOICE_AGENT"] = "m05"

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("KARYUK_VOICE_AGENT", None)
        else:
            os.environ["KARYUK_VOICE_AGENT"] = self._prev

    def test_enabled_and_opening_match_m05(self) -> None:
        self.assertTrue(m05_voice_enabled())
        self.assertEqual(employee_lang_code("Telugu"), "te")
        opening = spoken_opening("Telugu")
        self.assertIn("అనీత", opening)
        self.assertNotIn("Speak ONLY", opening)

    def test_instructions_are_the_m05_phone_prompt(self) -> None:
        text = phone_instructions("Telugu")
        self.assertIn("Anitha", text)
        self.assertIn("PHONE FACT SHEET", text)
        self.assertNotIn("models/gemini", text)

    @unittest.skipUnless(os.getenv("KARYUK_VOICE_LLM_FIRST") == "0", "M05 turn path only when LLM-first is off")
    @patch("app.services.voice.m05_sarvam.complete_chat", return_value="CSE ఫీజు సంవత్సరానికి ఒక లక్ష ఇరవై వేలు అండి.")
    def test_turn_uses_sarvam_not_hospital_script(self, chat) -> None:
        call = SimpleNamespace(
            captured_fields={
                "employee_language": "Telugu",
                "conversation_language": "te-IN",
                "inbound_chat": {"turns": []},
            },
            transcript="",
            summary="",
            outcome=None,
            finalized_at=None,
            duration_seconds=0,
        )
        reply, hang = process_inbound_speech(
            _FakeSession(),
            call,
            caller_text="సీఎస్ఈ ఫీజు ఎంత?",
            stt_language="te-IN",
        )
        self.assertFalse(hang)
        self.assertIn("లక్ష", reply)
        self.assertNotIn("చెక్-ఇన్", reply)
        self.assertEqual(call.captured_fields.get("speech_stack"), "sarvam-m05")
        self.assertTrue(chat.called)
        system = chat.call_args.args[0][0]["content"]
        self.assertIn("PHONE FACT SHEET", system)
        self.assertIn("Anitha", system)
