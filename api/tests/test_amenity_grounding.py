"""Amenity/feature grounding."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.schemas.business_profile import BusinessProfile
from app.services.business_profile_render import render_profile_facts
from app.services.voice.voice_fact_guard import reply_asserts_ungrounded_feature
from app.services.voice.voice_grounding_guard import sentence_fails_grounding

FIXTURES = Path(__file__).parent / "fixtures"


class AmenityGroundingTests(unittest.TestCase):
    def test_pool_not_in_facts(self) -> None:
        prof = json.loads((FIXTURES / "vfarms_no_pool_profile.json").read_text())
        facts = render_profile_facts(BusinessProfile.from_snapshot(prof))
        bad = "అవును అండి, మాకు swimming pool ఉంది."
        self.assertTrue(reply_asserts_ungrounded_feature(bad, facts))
        fail, reasons = sentence_fails_grounding(
            bad, spoken_facts=facts, fields={}, caller_text="pool ఉందా?"
        )
        self.assertTrue(fail)
        self.assertIn("amenity_ungrounded", reasons)

    def test_pool_in_vfarms_facts_ok(self) -> None:
        prof = json.loads((FIXTURES / "vfarms_profile.json").read_text())
        facts = render_profile_facts(BusinessProfile.from_snapshot(prof))
        ok = "అవును అండి, మాకు swimming pool ఉంది."
        self.assertFalse(reply_asserts_ungrounded_feature(ok, facts))


if __name__ == "__main__":
    unittest.main()