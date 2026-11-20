"""One-off: remap wrong ExoPhone E.164 (+91404590002) to +914045900002 (0404590002)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from sqlalchemy import create_engine, select

from app.config import get_settings
from app.models.platform import PhoneNumber
from app.services.phone import e164_variants, national_exophone_display, normalize_e164
from sqlalchemy.orm import Session

WRONG = "+91404590002"
CANON = "+914045900002"


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        fixed = 0
        for wrong in (WRONG, "+910404590002"):
            rows = db.scalars(select(PhoneNumber).where(PhoneNumber.e164 == wrong)).all()
            for row in rows:
                row.e164 = CANON
                row.inbound_enabled = True
                fixed += 1
        # Dedupe: if both wrong and canon existed, merge handled by unique? Check no duplicate workspace
        db.commit()
        active = db.scalars(
            select(PhoneNumber).where(PhoneNumber.inbound_enabled.is_(True))
        ).all()
        print("fixed_rows", fixed)
        for r in active:
            print(
                "active",
                r.workspace_id,
                r.e164,
                "dial",
                national_exophone_display(r.e164),
            )
        assert CANON in e164_variants("0404590002")
        assert normalize_e164("0404590002") == CANON
    return 0


if __name__ == "__main__":
    raise SystemExit(main())