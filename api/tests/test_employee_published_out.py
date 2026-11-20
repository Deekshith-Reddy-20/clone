"""Employee API exposes published snapshot vs draft for Team UI."""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register tables on Base.metadata
from app.database import Base
from app.models import Employee
from app.models.enums import CallMode
from app.models.identity import Workspace
from app.routers.employees import _employee_out
from app.schemas.employee import EmployeeCreate, EmployeeDraftUpdate
from app.services.employees import create_employee, get_draft, publish_employee, update_draft


class EmployeePublishedOutTests(unittest.TestCase):
    def test_published_snapshot_differs_from_draft(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            ws = Workspace(id=uuid.uuid4(), name="Publish test")
            db.add(ws)
            db.commit()
            create_employee(
                db,
                ws.id,
                EmployeeCreate(
                    brief="Resort receptionist for published snapshot tests.",
                    language="Telugu",
                    mode=CallMode.instant,
                ),
            )
            emp = db.scalars(select(Employee).where(Employee.workspace_id == ws.id)).first()
            self.assertIsNotNone(emp)
            draft = get_draft(db, emp.id)
            self.assertIsNotNone(draft)
            update_draft(
                db,
                workspace_id=ws.id,
                employee_id=emp.id,
                body=EmployeeDraftUpdate(mode=CallMode.inbound, revision=draft.revision),
            )
            publish_employee(db, ws.id, emp.id)
            draft = get_draft(db, emp.id)
            update_draft(
                db,
                workspace_id=ws.id,
                employee_id=emp.id,
                body=EmployeeDraftUpdate(mode=CallMode.instant, revision=draft.revision),
            )
            db.refresh(emp)
            out = _employee_out(db, emp)
            self.assertIsNotNone(out.published_snapshot)
            self.assertIsNotNone(out.draft)
            self.assertEqual(out.published_snapshot.mode, CallMode.inbound)
            self.assertEqual(out.draft.mode, CallMode.instant)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
