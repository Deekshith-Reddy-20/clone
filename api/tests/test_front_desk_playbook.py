from __future__ import annotations

import unittest

from app.services.voice.spoken_policy import build_reception_system_prompt, render_front_desk_playbook
from app.services.voice.voice_leads import is_human_transfer_request, transfer_reply


class FrontDeskPlaybookTests(unittest.TestCase):
    def test_template_fills_name_business(self) -> None:
        out = render_front_desk_playbook(
            agent_name="Maya",
            business_name="V Farms Resort",
            facts="Near Medchal.",
        )
        self.assertIn("Maya", out)
        self.assertIn("V Farms Resort", out)
        self.assertIn("save_lead", out)
        self.assertIn("Medchal", out)

    def test_system_prompt_language(self) -> None:
        p = build_reception_system_prompt(
            agent_name="Maya",
            business_name="V Farms",
            facts="Pool 8:30 AM.",
            reply_language="te-IN",
            vertical="lodging",
        )
        self.assertIn("Telugu", p)
        self.assertIn("Lodging", p)

    def test_transfer_request(self) -> None:
        self.assertTrue(is_human_transfer_request("Please transfer me to a human agent"))
        self.assertIn("staff", transfer_reply("te-IN"))


if __name__ == "__main__":
    unittest.main()