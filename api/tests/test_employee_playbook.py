import unittest

from app.services.voice.employee_playbook import (
    booking_intent,
    should_run_booking_flow,
    try_knowledge_snippet_reply,
)
from tests.legacy_fastpath import skip_unless_legacy


@skip_unless_legacy
class PlaybookTests(unittest.TestCase):
    def test_booking_not_for_general_question(self) -> None:
        fields = {"employee_brief": "You are a coaching center agent."}
        self.assertFalse(should_run_booking_flow(fields, "What are your batch timings?"))

    def test_booking_for_availability(self) -> None:
        fields = {"employee_brief": "Resort agent"}
        self.assertTrue(should_run_booking_flow(fields, "any rooms available this weekend?"))

    def test_snippet_from_website(self) -> None:
        web = "- Pool hours: 7 AM to 9 PM daily.\n- Location: Near Shamshabad highway."
        reply = try_knowledge_snippet_reply(
            "What time does the pool open?",
            brief="V Farms Resort",
            website_knowledge=web,
            lang="en-IN",
        )
        self.assertIsNotNone(reply)
        self.assertIn("pool", reply.lower())
        self.assertIn("7", reply)

    def test_booking_intent_variants(self) -> None:
        self.assertTrue(booking_intent("నాకు అవైలబిలిటీ ఉందా"))
        self.assertFalse(booking_intent("clinic appointment demo class"))

    def test_counselling_time_without_hostel_fee(self) -> None:
        web = "Counselling sessions are held every Saturday at 10 AM."
        reply = try_knowledge_snippet_reply(
            "When is counselling?",
            brief="Admissions desk",
            website_knowledge=web,
            lang="en-IN",
        )
        self.assertIsNotNone(reply)
        self.assertIn("Saturday", reply)
        missing = try_knowledge_snippet_reply(
            "What is the hostel fee?",
            brief="Admissions desk",
            website_knowledge=web,
            lang="en-IN",
        )
        self.assertIsNone(missing)


if __name__ == "__main__":
    unittest.main()