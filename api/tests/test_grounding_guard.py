"""General grounding guard — prices, hours, availability, dates."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.schemas.business_profile import BusinessProfile
from app.services.business_profile_render import render_profile_facts
from app.services.voice.voice_grounding_guard import sentence_fails_grounding

FIXTURES = Path(__file__).parent / "fixtures"


class GroundingGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        prof = json.loads((FIXTURES / "vfarms_profile.json").read_text())
        self.facts = render_profile_facts(BusinessProfile.from_snapshot(prof))
        self.fields: dict = {"inbound_booking": {"check_in": "2026-11-22", "guest_count": 4}}

    def test_hours_not_in_facts(self) -> None:
        bad = "మా resort ఉదయం 9 గంటల నుంచి రాత్రి 9 గంటల వరకు open ఉంటుంది అండి."
        fail, reasons = sentence_fails_grounding(
            bad, spoken_facts=self.facts, fields=self.fields, caller_text="opening?"
        )
        self.assertTrue(fail)
        self.assertTrue(reasons)

    def test_rooms_available_fails(self) -> None:
        bad = "22nd November కి 4 rooms available అండి."
        fail, reasons = sentence_fails_grounding(
            bad,
            spoken_facts=self.facts,
            fields={**self.fields, "availability_not_configured": True},
            caller_text="4 వస్తారు.",
        )
        self.assertTrue(fail)
        self.assertIn("availability_ungrounded", reasons)

    def test_december_not_in_state(self) -> None:
        bad = "22nd November నుంచి 11th December వరకు booking."
        fail, reasons = sentence_fails_grounding(
            bad, spoken_facts=self.facts, fields=self.fields, caller_text="book చేయండి"
        )
        self.assertTrue(fail)

    def test_telugu_december_not_in_state(self) -> None:
        bad = "22 నవంబర్ నుంచి 11 డిసెంబర్ వరకు booking."
        fail, _ = sentence_fails_grounding(
            bad, spoken_facts=self.facts, fields=self.fields, caller_text="book చేయండి"
        )
        self.assertTrue(fail)


if __name__ == "__main__":
    unittest.main()