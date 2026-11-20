import os
import unittest
from datetime import date

from app.services.voice.voice_dates import calendar_block_for_prompt, resolve_dates


class VoiceDatesTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["KARYUK_CALL_DATE"] = "2026-11-20"

    def tearDown(self) -> None:
        os.environ.pop("KARYUK_CALL_DATE", None)

    def test_ellundi_sunday(self) -> None:
        anchor = date(2026, 11, 20)
        r = resolve_dates("ఎల్లుండి వద్దాం", anchor=anchor)
        self.assertEqual(r.check_in, "2026-11-22")

    def test_this_saturday(self) -> None:
        anchor = date(2026, 11, 20)
        r = resolve_dates("ఈ శనివారం check-in", anchor=anchor)
        self.assertEqual(r.check_in, "2026-11-21")

    def test_two_nights_from_ellundi(self) -> None:
        anchor = date(2026, 11, 20)
        r = resolve_dates("2 nights from ఎల్లుండి", anchor=anchor)
        self.assertEqual(r.check_in, "2026-11-22")
        self.assertEqual(r.check_out, "2026-11-24")

    def test_calendar_has_today(self) -> None:
        block = calendar_block_for_prompt(anchor=date(2026, 11, 20), days=3)
        self.assertIn("2026-11-20", block)
        self.assertIn("ఎల్లుండి", block)


if __name__ == "__main__":
    unittest.main()