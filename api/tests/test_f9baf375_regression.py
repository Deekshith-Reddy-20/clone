"""Regression cases from live call f9baf375 (echo / false Hindi)."""
import unittest

from app.services.voice.call_turn_policy import reject_turn_reason


class F9baf375Regression(unittest.TestCase):
    def test_13_char_hindi_rejected(self) -> None:
        for sample in ("क्या बात है", "हाँ जी सर", "ठीक है सर"):
            reason = reject_turn_reason(
                sample,
                employee_language="Telugu",
                conversation_language="te-IN",
            )
            self.assertIn(
                reason,
                ("hindi_noise_telugu_line", "spurious", "too_short", "low_signal"),
                msg=sample,
            )

    def test_telugu_question_accepted(self) -> None:
        q = "ఈ వీకెండ్ గదులు ఉన్నాయా?"
        self.assertIsNone(
            reject_turn_reason(q, employee_language="Telugu", conversation_language="te-IN")
        )

    def test_english_question_accepted(self) -> None:
        q = "Any rooms available this weekend?"
        self.assertIsNone(
            reject_turn_reason(q, employee_language="Telugu", conversation_language="te-IN")
        )

    def test_short_hindi_fee_question_accepted(self) -> None:
        q = "फीस कितनी है?"
        self.assertIsNone(
            reject_turn_reason(q, employee_language="Telugu", conversation_language="te-IN")
        )

    def test_call_9be90c2b_hindi_ack_not_accepted(self) -> None:
        reason = reject_turn_reason(
            "हाँ जी हाँ जी हाँ जी",
            employee_language="Telugu",
            conversation_language="hi-IN",
        )
        self.assertIsNotNone(reason)


if __name__ == "__main__":
    unittest.main()