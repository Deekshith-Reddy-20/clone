import unittest
from unittest.mock import MagicMock

from app.services.employee_knowledge import (
    combine_supplemental_knowledge,
    knowledge_metrics,
    supplemental_for_inbound,
)


class EmployeeKnowledgeTests(unittest.TestCase):
    def test_metrics_include_brief(self) -> None:
        m = knowledge_metrics(
            brief="Hospital front desk agent with OPD timings.",
            website_knowledge="",
            workspace_knowledge=None,
        )
        self.assertGreater(m["total_grounding_chars"], 20)
        self.assertEqual(m["website_chars"], 0)

    def test_combine_supplemental(self) -> None:
        out = combine_supplemental_knowledge("Site facts", "### FAQ\nCheck-in 2pm")
        self.assertIn("Site facts", out)
        self.assertIn("Check-in", out)

    def test_inbound_backfill_workspace(self) -> None:
        db = MagicMock()
        row = MagicMock()
        row.title = "FAQ"
        row.content = "OPD 9 AM to 5 PM"
        db.scalars.return_value.all.return_value = [row]
        supplemental, web, ws = supplemental_for_inbound(
            {"brief": "Hospital", "website_knowledge": ""},
            db,
            "00000000-0000-0000-0000-000000000001",
        )
        self.assertIn("OPD", supplemental)
        self.assertIn("OPD", ws)
        self.assertEqual(web, "")


if __name__ == "__main__":
    unittest.main()