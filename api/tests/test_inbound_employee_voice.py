"""Hire → publish → inbound: Sarvam voice travels with the employee snapshot."""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock, patch

from app.models import Employee, EmployeeDraft
from app.models.enums import EmployeeStatus
from app.services.calls import _employee_snapshot
from app.services.employees import publish_employee
from app.services.voice.voice_catalog import resolve_tts_speaker


class InboundEmployeeVoiceTests(unittest.TestCase):
    def test_resolve_tts_speaker_female_default(self) -> None:
        self.assertEqual(resolve_tts_speaker("priya"), "priya")
        self.assertEqual(resolve_tts_speaker("bad-id", gender_preference="female"), "priya")

    def test_publish_pins_tts_speaker(self) -> None:
        ws = uuid.uuid4()
        emp_id = uuid.uuid4()
        employee = Employee(id=emp_id, workspace_id=ws, status=EmployeeStatus.draft)
        draft = EmployeeDraft(
            employee_id=emp_id,
            workspace_id=ws,
            brief="Resort front desk assistant for bookings.",
            language="Telugu",
            natural_spoken=True,
            tts_speaker="aditya",
        )
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        with (
            patch("app.services.employees.get_employee", return_value=employee),
            patch("app.services.employees.get_draft", return_value=draft),
        ):
            version = publish_employee(db, ws, emp_id)
        self.assertEqual(version.snapshot.get("tts_speaker"), "aditya")
        self.assertEqual(version.snapshot.get("version_number"), 1)

    def test_snapshot_from_active_version_has_speaker(self) -> None:
        db = MagicMock()
        emp_id = uuid.uuid4()
        ver_id = uuid.uuid4()
        employee = Employee(
            id=emp_id,
            workspace_id=uuid.uuid4(),
            status=EmployeeStatus.published,
            active_version_id=ver_id,
        )
        version = MagicMock()
        version.snapshot = {
            "brief": "Resort",
            "language": "Telugu",
            "tts_speaker": "priya",
            "revision": 2,
        }

        def _get(model, pk):
            if pk == ver_id:
                return version
            return None

        db.get = _get
        snap = _employee_snapshot(db, employee)
        self.assertEqual(snap["tts_speaker"], "priya")


if __name__ == "__main__":
    unittest.main()