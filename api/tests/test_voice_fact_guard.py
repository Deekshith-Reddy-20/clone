import unittest

from app.services.voice.voice_fact_guard import (
    caller_asks_missing_fact,
    classify_save_lead_miss,
    reply_invented_negative,
    reply_mentions_ungrounded_entity,
)


class VoiceFactGuardTests(unittest.TestCase):
    def test_helipad_not_in_facts(self) -> None:
        facts = "Amenity: Swimming pool\nBusiness: V Farms"
        self.assertTrue(caller_asks_missing_fact("helipad ఉందా?", facts))
        reply = "మాకు helipad లేదు అండి"
        self.assertTrue(reply_mentions_ungrounded_entity(reply, facts))
        self.assertTrue(reply_invented_negative(reply, facts))
        self.assertEqual(
            classify_save_lead_miss("helipad?", reply, facts, save_lead_called=False),
            "a",
        )

    def test_rera_invented_negative(self) -> None:
        facts = "Business: Wayfinder Greens plots"
        reply = "We don't have RERA registration yet"
        self.assertTrue(reply_invented_negative(reply, facts))
        self.assertTrue(caller_asks_missing_fact("RERA number?", facts))

    def test_aviation_invented_negative_te(self) -> None:
        facts = "Program: CSE B.Tech"
        reply = "MBA aviation course మాకు లేదు అండి"
        self.assertTrue(reply_invented_negative(reply, facts))

    def test_explicit_deny_in_facts_ok(self) -> None:
        facts = "Amenity: no helipad on property"
        reply = "There is no helipad on the property."
        self.assertFalse(reply_invented_negative(reply, facts))

    def test_price_grounded_ok(self) -> None:
        facts = "Offering Standard room: from Rs 3500 per night"
        reply = "Rs 3500 per night weekday rate అండి"
        self.assertFalse(reply_mentions_ungrounded_entity(reply, facts))