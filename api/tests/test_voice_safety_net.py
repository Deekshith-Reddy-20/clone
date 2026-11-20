import unittest

from app.services.voice.voice_location_followup import (
    agent_offered_whatsapp,
    caller_accepted_whatsapp_offer,
    whatsapp_send_consented,
)
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

    def test_whatsapp_requires_offer_and_accept(self) -> None:
        self.assertTrue(agent_offered_whatsapp("Shall I send the location on WhatsApp?"))
        self.assertFalse(agent_offered_whatsapp("We are near Shamshabad airport."))
        self.assertTrue(caller_accepted_whatsapp_offer("yes please"))
        self.assertTrue(
            whatsapp_send_consented(
                "అవును",
                last_agent_reply="Location WhatsApp పంపమా?",
            )
        )
        self.assertFalse(
            whatsapp_send_consented(
                "ఈ శనివారం check-in అవుతుందా?",
                last_agent_reply="శనివారం check-in చేయొచ్చు.",
            )
        )


if __name__ == "__main__":
    unittest.main()