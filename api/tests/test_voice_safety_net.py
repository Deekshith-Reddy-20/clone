import unittest

from app.services.voice.voice_safety_net import (
    booking_create_intent,
    manager_callback_intent,
    safety_net_blocked,
)


class VoiceSafetyNetTests(unittest.TestCase):
    def test_booking_how_blocked(self) -> None:
        t = "booking ఎలా చేయాలి?"
        self.assertTrue(safety_net_blocked(t))
        self.assertFalse(booking_create_intent(t, {}))

    def test_manager_who_blocked(self) -> None:
        t = "manager ఎవరు?"
        self.assertTrue(safety_net_blocked(t))
        self.assertFalse(manager_callback_intent(t))

    def test_manager_callback_ok(self) -> None:
        self.assertTrue(manager_callback_intent("manager తో మాట్లాడాలి"))

    def test_past_booking_blocked(self) -> None:
        t = "last time I booked here it was nice"
        self.assertTrue(safety_net_blocked(t))
        self.assertFalse(booking_create_intent(t, {}))


if __name__ == "__main__":
    unittest.main()