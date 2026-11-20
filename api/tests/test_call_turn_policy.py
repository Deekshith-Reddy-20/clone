import unittest

from app.services.voice.call_turn_policy import (
    is_short_acknowledgment,
    reject_turn_reason,
    stt_language_for_reply,
)


class CallTurnPolicyTests(unittest.TestCase):
    def test_telugu_ack(self) -> None:
        self.assertTrue(is_short_acknowledgment("అవును"))
        self.assertIsNone(reject_turn_reason("అవును", employee_language="Telugu"))

    def test_hindi_noise_on_telugu_line(self) -> None:
        reason = reject_turn_reason("हाँ जी सर", employee_language="Telugu", conversation_language="te-IN")
        self.assertIn(reason, ("hindi_noise_telugu_line", "spurious", "hindi_ack_noise"))

    def test_short_hindi_hallucination(self) -> None:
        reason = reject_turn_reason("क्या बात है", employee_language="Telugu", conversation_language="te-IN")
        self.assertEqual(reason, "hindi_noise_telugu_line")

    def test_stt_tag_ignored_for_short_hindi(self) -> None:
        self.assertIsNone(
            stt_language_for_reply(
                "क्या बात है",
                "hi-IN",
                employee_language="Telugu",
                conversation_language="te-IN",
            )
        )

    def test_real_hindi_question(self) -> None:
        q = "क्या इस वीकेंड में कमरा उपलब्ध है?"
        self.assertIsNone(reject_turn_reason(q, employee_language="Telugu", conversation_language="te-IN"))


if __name__ == "__main__":
    unittest.main()