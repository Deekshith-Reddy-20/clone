import unittest
from datetime import date

from app.services.voice.booking_state import (
    BookingState,
    extract_dates,
    extract_guest_count,
    is_duplicate_utterance,
    merge_utterance,
    missing_fields,
)
from app.services.voice.inbound_booking import try_booking_turn


class BookingExtractionTests(unittest.TestCase):
    def test_guests_and_dates_telugu_english_mix(self) -> None:
        text = (
            "నాకు ఈ వీకెండ్ అవైలబిలిటీ ఉందా? మేము మొత్తం 15 మెంబర్స్ వస్తున్నాము. "
            "చెక్ ఇన్ తేది 22, చెక్ ఔట్ తేది 24"
        )
        self.assertEqual(extract_guest_count(text), 15)
        cin, cout = extract_dates(text)
        self.assertIsNotNone(cin)
        self.assertIsNotNone(cout)
        st = merge_utterance(BookingState(), text)
        self.assertEqual(st.guest_count, 15)
        self.assertEqual(missing_fields(st), [])

    def test_guest_only_turn_keeps_dates(self) -> None:
        st = merge_utterance(BookingState(), "22 నుంచి 24 వరకు")
        st.day_only_range = True
        st = merge_utterance(st, "30 మంది")
        self.assertEqual(st.guest_count, 30)
        self.assertIsNotNone(st.check_in)
        self.assertIsNotNone(st.check_out)

    def test_merge_across_turns(self) -> None:
        st = merge_utterance(BookingState(), "15 members this weekend")
        st = merge_utterance(st, "check in 22 checkout 24")
        self.assertEqual(st.guest_count, 15)
        self.assertIsNotNone(st.check_in)
        self.assertIsNotNone(st.check_out)

    def test_hindi_guest_count(self) -> None:
        text = "क्या इस वीकेंड में पंद्रह लोगों के लिए कमरा है?"
        self.assertEqual(extract_guest_count(text), 15)

    def test_duplicate_utterance(self) -> None:
        st = BookingState()
        st = merge_utterance(st, "hello there")
        self.assertTrue(is_duplicate_utterance(st, "hello there"))

    def test_booking_turn_full_details_fast_path(self) -> None:
        fields: dict = {}
        text = "We are 15 guests, check in 22 check out 24 November"
        reply, hangup, used_llm = try_booking_turn(
            caller_text=text,
            lang="te-IN",
            fields=fields,
            website_knowledge="V Farms Resort rooms",
        )
        self.assertFalse(used_llm)
        self.assertFalse(hangup)
        self.assertIn("బుక్", reply) or self.assertIn("?", reply)  # type: ignore[misc]


class BookingDateTests(unittest.TestCase):
    def test_pair_range(self) -> None:
        cin, cout = extract_dates("22 నుంచి 24 వరకు")
        self.assertIsNotNone(cin)
        self.assertIsNotNone(cout)
        if cin and cout:
            d0 = date.fromisoformat(cin)
            d1 = date.fromisoformat(cout)
            self.assertLess(d0, d1)


if __name__ == "__main__":
    unittest.main()