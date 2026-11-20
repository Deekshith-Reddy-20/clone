"""Booking slot merge and mapping."""

from __future__ import annotations

import unittest

from app.services.voice.booking_state import BOOKING_KEY, load_booking
from app.services.voice.voice_booking_slots import (
    apply_slot_merge,
    confirmation_readback,
    format_booking_slot_block,
    missing_booking_slots,
)


class BookingSlotTests(unittest.TestCase):
    def test_guest_answer_when_asked_nights(self) -> None:
        fields = {
            BOOKING_KEY: {
                "check_in": "2026-11-22",
                "last_slot_asked": "nights",
            },
            "caller_e164": "+919876543210",
        }
        fields = apply_slot_merge(
            fields,
            "4 వస్తారు.",
            last_agent_reply="ఎన్ని nights అండి?",
        )
        st = load_booking(fields)
        self.assertEqual(st.guest_count, 4)
        self.assertIn("nights", missing_booking_slots(st, fields))

    def test_slot_block(self) -> None:
        fields = {
            BOOKING_KEY: {"check_in": "2026-11-22", "guest_count": 4},
            "caller_e164": "+919876543210",
        }
        block = format_booking_slot_block(load_booking(fields), fields)
        self.assertIn("BOOKING:", block)
        self.assertIn("guests=4", block)
        self.assertIn("nights=MISSING", block)
        self.assertIn("NEXT: nights", block)
        self.assertIn("ఆదివారం", block)

    def test_spoken_date_no_abbrev(self) -> None:
        from datetime import date

        from app.services.voice.voice_booking_slots import spoken_stay_date

        s = spoken_stay_date(date(2026, 11, 22), lang="te-IN", anchor=date(2026, 11, 20))
        self.assertIn("ఆదివారం", s)
        self.assertIn("November", s)
        self.assertNotRegex(s, r"\bNov\b")
        self.assertNotIn("2026", s)

    def test_readback(self) -> None:
        st = load_booking(
            {
                BOOKING_KEY: {
                    "check_in": "2026-11-22",
                    "check_out": "2026-11-24",
                    "nights": 2,
                    "guest_count": 4,
                }
            }
        )
        rb = confirmation_readback(st, "te-IN")
        self.assertIn("22", rb)
        self.assertIn("2 nights", rb)
        self.assertIn("4 guests", rb)
        self.assertIn("పెట్టమంటారా", rb)
        self.assertIn("ఆదివారం", rb)


if __name__ == "__main__":
    unittest.main()