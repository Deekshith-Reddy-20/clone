"""Regression: V Farms transcript — office number, location, compliments."""

from __future__ import annotations

from tests.legacy_fastpath import skip_unless_legacy

import unittest

from app.services.voice.employee_playbook import (
    _sanitize_location_phrase,
    is_business_contact_question,
    is_caller_compliment,
    try_business_contact_reply,
    try_grounded_employee_reply,
    try_personal_boundary_reply,
    try_reception_smalltalk_reply,
)

KNOW = (
    "V Farms Resort near Medchal, Telangana. "
    "Hello, welcome to V-Farms near Medchal. "
    "Reception: 04045900002. Check-in 2pm."
)
BRIEF = "Your name is Maya for V Farms Resort."


@skip_unless_legacy
class VfarmsReceptionTranscriptTests(unittest.TestCase):
    def test_office_number_not_booking(self) -> None:
        q = "సరే, మీ office number చెప్పగలరా?"
        self.assertTrue(is_business_contact_question(q))
        reply = try_grounded_employee_reply(
            q,
            brief=BRIEF,
            website_knowledge=KNOW,
            lang="te-IN",
            vertical="lodging",
        )
        self.assertIsNotNone(reply)
        self.assertTrue("040459000" in reply.replace(" ", "") or "40459000" in reply.replace(" ", ""))
        self.assertNotIn("చెక్-ఇన్", reply)

    def test_location_strips_welcome(self) -> None:
        self.assertNotIn("Hello", _sanitize_location_phrase("Hello, welcome to V-Farms near Medchal, Telangana."))

    def test_location_confirm(self) -> None:
        r = try_reception_smalltalk_reply(
            "అది మొత్తం మీ location-ఆ?",
            brief=BRIEF,
            website_knowledge=KNOW,
            lang="te-IN",
        )
        self.assertIsNotNone(r)
        self.assertIn("అవును", r)
        self.assertIn("Medchal", r)

    def test_age_compliment_not_personal_refusal(self) -> None:
        q = "మీ వయసు రా బాగుంది."
        self.assertTrue(is_caller_compliment(q))
        self.assertIsNone(try_personal_boundary_reply(q, "te-IN"))

    def test_post_booking_number_request(self) -> None:
        q = "మర్చిపోయాను, మీ number ఇవ్వగలరా నాకు కొంచెం?"
        fields = {"inbound_booking": {"booking_ref": "VF-TEST", "booking_confirmed": True}}
        reply = try_business_contact_reply(
            q,
            brief=BRIEF,
            website_knowledge=KNOW,
            lang="te-IN",
            fields=fields,
        )
        self.assertIsNotNone(reply)
        self.assertTrue("040459000" in reply.replace(" ", "") or "40459000" in reply.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()