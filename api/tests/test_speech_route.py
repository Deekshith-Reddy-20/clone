import unittest

from app.services.voice.speech_route import (
    apply_explicit_language_switch,
    employee_default_bcp47,
    speech_stack_for_bcp47,
)


class SpeechRouteTests(unittest.TestCase):
    def test_telugu_sarvam(self) -> None:
        self.assertEqual(speech_stack_for_bcp47("te-IN"), "sarvam")

    def test_hindi_sarvam(self) -> None:
        self.assertEqual(speech_stack_for_bcp47("hi-IN"), "sarvam")

    def test_english_sarvam(self) -> None:
        self.assertEqual(speech_stack_for_bcp47("en-IN"), "sarvam")

    def test_explicit_telugu_switch(self) -> None:
        self.assertEqual(apply_explicit_language_switch("తెలుగులో చెప్పండి", "en-IN"), "te-IN")

    def test_employee_telugu_default(self) -> None:
        self.assertEqual(employee_default_bcp47("Telugu"), "te-IN")


if __name__ == "__main__":
    unittest.main()