import unittest

from app.services.voice.sarvam import avoid_repeat_reply, resolve_call_language


class CallLanguageTests(unittest.TestCase):
    def test_telugu_employee_rejects_hindi_stt_noise(self) -> None:
        lang = resolve_call_language(
            caller_text="हाँ जी",
            conversation_language="te-IN",
            employee_language="Telugu",
            stt_language="hi-IN",
        )
        self.assertEqual(lang, "te-IN")

    def test_tamil_stt_is_spurious(self) -> None:
        from app.services.voice.sarvam import is_spurious_stt_snippet

        self.assertTrue(is_spurious_stt_snippet("ஆ சரிங்க சார்"))

    def test_telugu_script(self) -> None:
        lang = resolve_call_language(
            caller_text="ఈ వీకెండ్ అవైలబిలిటీ ఉందా?",
            conversation_language=None,
            employee_language="Telugu",
            stt_language="en-IN",
        )
        self.assertEqual(lang, "te-IN")

    def test_hindi_caller_telugu_employee(self) -> None:
        lang = resolve_call_language(
            caller_text="क्या इस वीकेंड में पंद्रह लोगों के लिए कमरा है?",
            conversation_language="te-IN",
            employee_language="Telugu",
            stt_language="hi-IN",
        )
        self.assertEqual(lang, "hi-IN")

    def test_hindi_caller_hindi_employee(self) -> None:
        lang = resolve_call_language(
            caller_text="मुझे कल आना है क्या कमरा मिलेगा",
            conversation_language=None,
            employee_language="Hindi",
            stt_language="hi-IN",
        )
        self.assertEqual(lang, "hi-IN")

    def test_english_general(self) -> None:
        lang = resolve_call_language(
            caller_text="What are your pool timings?",
            conversation_language=None,
            employee_language="English",
            stt_language="en-IN",
        )
        self.assertEqual(lang, "en-IN")

    def test_english_on_telugu_employee(self) -> None:
        lang = resolve_call_language(
            caller_text="pool timings please",
            conversation_language="te-IN",
            employee_language="Telugu",
            stt_language="en-IN",
        )
        self.assertEqual(lang, "te-IN")

    def test_no_repeat(self) -> None:
        a = "Sure. What date would you like to check in?"
        b = avoid_repeat_reply(a, a)
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()