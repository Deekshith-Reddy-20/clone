"""Booking slot merge and mapping."""

from __future__ import annotations

import unittest

from app.services.voice.booking_state import BOOKING_KEY, load_booking
from app.services.voice.voice_booking_slots import (
    apply_slot_merge,
    confirmation_readback,
    extract_nights_answer,
    format_booking_slot_block,
    handle_booking_slot_turn,
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

    def test_bare_nights_computes_checkout(self) -> None:
        fields = {
            BOOKING_KEY: {
                "check_in": "2026-11-22",
                "last_slot_asked": "nights",
            },
            "caller_e164": "+919876543210",
        }
        fields = apply_slot_merge(
            fields,
            "2",
            last_agent_reply="ఎన్ని nights అండి?",
        )
        st = load_booking(fields)
        self.assertEqual(st.nights, 2)
        self.assertEqual(st.check_out, "2026-11-24")
        self.assertNotIn("nights", missing_booking_slots(st, fields))

    def test_telugu_nights_computes_checkout(self) -> None:
        self.assertEqual(extract_nights_answer("రెండు"), 2)
        fields = {
            BOOKING_KEY: {
                "check_in": "2026-11-22",
                "last_slot_asked": "nights",
            },
            "caller_e164": "+919876543210",
        }
        fields = apply_slot_merge(
            fields,
            "రెండు అండి",
            last_agent_reply="ఎన్ని nights అండి?",
        )
        st = load_booking(fields)
        self.assertEqual(st.nights, 2)
        self.assertEqual(st.check_out, "2026-11-24")

    def test_progress_ack_asks_only_next_slot(self) -> None:
        fields = {
            BOOKING_KEY: {
                "check_in": "2026-11-23",
                "nights": 4,
                "check_out": "2026-11-27",
                "last_slot_asked": "nights",
            },
            "caller_e164": "+919876543210",
            "employee_brief": "V Farms resort lodging",
            "tool_log": [],
        }
        reply, _, hangup = handle_booking_slot_turn(
            None,
            None,
            fields,
            "4 nights",
            "te-IN",
            "ఎన్ని nights అండి?",
            lambda *a, **k: ("", fields, False),
            miss_before=["nights", "guests"],
        )
        self.assertFalse(hangup)
        self.assertIsNotNone(reply)
        self.assertIn("4 nights", reply or "")
        self.assertIn("మంది", reply or "")
        self.assertNotIn("check-out", (reply or "").lower())

    def test_unclear_crumb_does_not_fake_note(self) -> None:
        fields = {
            BOOKING_KEY: {"last_slot_asked": "check_in", "last_prompt": "check_in"},
            "caller_e164": "+919876543210",
            "employee_brief": "V Farms resort lodging",
            "tool_log": [],
        }
        reply, _, hangup = handle_booking_slot_turn(
            None,
            None,
            fields,
            "నెంబర్",
            "te-IN",
            "check-in తేదీ చెప్పండి అండి.",
            lambda *a, **k: ("", fields, False),
            miss_before=["check_in", "nights", "guests"],
        )
        self.assertFalse(hangup)
        self.assertIn("check-in", (reply or "").lower())
        self.assertNotIn("నెంబర్ నోట్", reply or "")
        self.assertNotIn("noted your number", (reply or "").lower())

    def test_confirm_stays_on_line_after_enquiry(self) -> None:
        fields = {
            BOOKING_KEY: {
                "check_in": "2026-11-22",
                "check_out": "2026-11-24",
                "nights": 2,
                "guest_count": 4,
                "awaiting_confirmation": True,
                "last_slot_asked": "confirm",
            },
            "caller_e164": "+919876543210",
            "employee_brief": "V Farms resort lodging",
            "tool_log": [],
        }

        def _exec(name, args, tool_source="slot_flow"):
            fields["tool_log"] = list(fields.get("tool_log") or []) + [{"name": name}]
            fields[BOOKING_KEY] = {
                **(fields.get(BOOKING_KEY) or {}),
                "booking_confirmed": True,
                "awaiting_confirmation": False,
            }
            return "noted", fields, False

        reply, fields2, hangup = handle_booking_slot_turn(
            None,
            None,
            fields,
            "ఆ",
            "te-IN",
            "ఇలా request పెట్టమంటారా?",
            _exec,
        )
        self.assertFalse(hangup)
        self.assertIn("note", (reply or "").lower())
        self.assertTrue(load_booking(fields2).booking_confirmed)

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