"""Website/PDF-grounded answers: polite gaps and personal boundaries."""

from __future__ import annotations

import unittest

from app.services.voice.employee_playbook import (
    is_private_or_personal_request,
    polite_not_in_knowledge_reply,
    try_knowledge_gap_reply,
    try_personal_boundary_reply,
)


class HumanKnowledgeBoundaryTests(unittest.TestCase):
    KNOW = "Swimming pool opens daily at 8:30 AM. Closes at 10 PM."

    def test_personal_number_refused(self) -> None:
        self.assertTrue(is_private_or_personal_request("What is your personal phone number sir?"))
        reply = try_personal_boundary_reply("What is your mobile number?", "en-IN")
        self.assertIsNotNone(reply)
        self.assertIn("personal", reply.lower())

    def test_business_contact_not_personal(self) -> None:
        self.assertFalse(
            is_private_or_personal_request("What is the resort reception phone number?")
        )

    def test_missing_fact_polite(self) -> None:
        reply = try_knowledge_gap_reply(
            "What is the spa price per hour?",
            brief="Resort desk",
            website_knowledge=self.KNOW,
            lang="en-IN",
        )
        self.assertIsNotNone(reply)
        self.assertIn("don't have", reply.lower())

    def test_known_pool_not_gap(self) -> None:
        reply = try_knowledge_gap_reply(
            "What time does the pool open in the morning?",
            brief="Resort",
            website_knowledge=self.KNOW,
            lang="en-IN",
        )
        self.assertIsNone(reply)

    def test_telugu_polite_missing(self) -> None:
        out = polite_not_in_knowledge_reply("te-IN")
        self.assertIn("లేవండి", out)


if __name__ == "__main__":
    unittest.main()