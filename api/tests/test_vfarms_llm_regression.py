"""Phase A/G: V Farms transcript must not leak bypass strings (LLM-first + mocked replies)."""

from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import json

from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.voice_output_guard import guard_reply_rejected

DATA_PATH = Path(__file__).parent / "conversations" / "vfarms_regression.json"


def _call(brief: str, facts: str) -> MagicMock:
    call = MagicMock()
    call.employee_id = None
    call.workspace_id = None
    call.captured_fields = {
        "employee_brief": brief,
        "employee_language": "Telugu",
        "employee_website_knowledge": facts,
        "employee_natural_spoken": True,
        "employee_mode": "lodging",
        "conversation_language": "te-IN",
        "inbound_chat": {"turns": []},
    }
    call.transcript = ""
    call.summary = ""
    call.duration_seconds = 0
    call.outcome = None
    return call


class VfarmsLlmRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        os.environ["KARYUK_VOICE_LLM_FIRST"] = "1"

    def test_guard_blocks_brief_leak(self) -> None:
        _, rej = guard_reply_rejected(
            "Your name is maya for V Farms Resort.",
            brief=self.data["employee"]["brief"],
            lang="te-IN",
        )
        self.assertTrue(rej)

    @patch("app.services.voice.inbound_llm_engine.generate_inbound_llm_turn")
    def test_transcript_forbidden_strings(self, mock_llm) -> None:
        facts = self.data["employee"]["facts"]
        brief = self.data["employee"]["brief"]
        replies = [
            "V Farms Resort అండి — farm-stay vibe. Stay కోసం dates చెప్తారా?",
            "మా property Medchal లో ఉంది, ORR exit దగ్గర.",
            "ORR Medchal exit landmark — city నుంచి 28 km అండి.",
            "అవును, Medchal side లోనే.",
            "Weekday rooms 3500 నుంచి per night అండి.",
            "ఒక రాత్రికి 3500 నుంచి; exact కోసం dates చెప్పండి.",
        ]
        from app.services.voice.voice_llm_router import LlmTurnResult

        mock_llm.side_effect = [LlmTurnResult(r, 42.0, "mock") for r in replies]

        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        call = _call(brief, facts)

        for i, step in enumerate(self.data["turns"]):
            reply, _ = process_inbound_speech(
                db,
                call,
                caller_text=step["caller"],
                stt_language="te-IN",
            )
            for bad in step.get("forbid_substrings", []):
                self.assertNotIn(bad, reply, f"turn {i+1}: {bad!r} in {reply!r}")
            needs = step.get("require_any", [])
            if needs:
                self.assertTrue(
                    any(n in reply for n in needs),
                    f"turn {i+1}: need one of {needs!r} in {reply!r}",
                )
            self.assertLessEqual(len(reply.split()), 45, f"turn {i+1} too long")


if __name__ == "__main__":
    unittest.main()