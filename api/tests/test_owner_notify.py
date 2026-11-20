import unittest

from app.config import Settings
from app.services.owner_notify import (
    channel_configured,
    manager_callback_minutes,
    owner_contact,
    owner_notify_channel_verified,
    send_test_notification,
)


class OwnerNotifyTests(unittest.TestCase):
    def test_unverified_no_minutes(self) -> None:
        wo = {"verified": {"email": False, "sms": False, "whatsapp": False}}
        contacts = {"email": "a@b.com", "sms": "", "whatsapp": ""}
        s = Settings(
            owner_notify_email="a@b.com",
            smtp_host="smtp.example.com",
            smtp_user="u",
            smtp_password="p",
        )
        self.assertIsNone(owner_notify_channel_verified(wo, contacts, s))
        self.assertIsNone(manager_callback_minutes(wo, contacts, s))

    def test_verified_email_allows_minutes(self) -> None:
        wo = {"verified": {"email": True, "sms": False, "whatsapp": False}}
        contacts = owner_contact(wo, Settings(owner_notify_email="a@b.com"))
        s = Settings(
            owner_notify_email="a@b.com",
            smtp_host="smtp.example.com",
            smtp_user="u",
            smtp_password="p",
        )
        self.assertEqual(owner_notify_channel_verified(wo, contacts, s), "email")
        self.assertEqual(manager_callback_minutes(wo, contacts, s), 15)

    def test_no_credentials_not_configured(self) -> None:
        s = Settings(owner_notify_email="a@b.com", smtp_host="")
        contacts = owner_contact({}, s)
        status, ch = send_test_notification("email", settings=s, contacts=contacts)
        self.assertEqual(status, "not_configured")
        self.assertEqual(ch, "email")
        self.assertFalse(channel_configured("email", contacts, s))