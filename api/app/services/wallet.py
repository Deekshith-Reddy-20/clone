from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import WalletAccount, WalletLedgerEntry
from app.models.enums import LedgerEntryType


def ensure_wallet(db: Session, workspace_id: UUID, initial_paise: int = 5000) -> WalletAccount:
    account = db.execute(
        select(WalletAccount).where(WalletAccount.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if account:
        return account
    account = WalletAccount(workspace_id=workspace_id, balance_paise=initial_paise, reserved_paise=0)
    db.add(account)
    db.add(
        WalletLedgerEntry(
            workspace_id=workspace_id,
            entry_type=LedgerEntryType.credit,
            amount_paise=initial_paise,
            reference=f"seed-{workspace_id}",
            meta={"reason": "starter_credits"},
        )
    )
    db.commit()
    db.refresh(account)
    return account


def get_wallet(db: Session, workspace_id: UUID) -> WalletAccount:
    return ensure_wallet(db, workspace_id)


def top_up(db: Session, workspace_id: UUID, paise: int, reference: str | None = None) -> WalletAccount:
    account = ensure_wallet(db, workspace_id)
    ref = reference or f"topup-{uuid4()}"
    account.balance_paise += paise
    db.add(
        WalletLedgerEntry(
            workspace_id=workspace_id,
            entry_type=LedgerEntryType.credit,
            amount_paise=paise,
            reference=ref,
            meta={"sandbox": True},
        )
    )
    db.commit()
    db.refresh(account)
    return account


def ensure_call_credits(db: Session, workspace_id: UUID, paise: int) -> None:
    """In development, auto top-up so inbound Exotel tests are not blocked by empty wallet."""
    account = ensure_wallet(db, workspace_id)
    available = account.balance_paise - account.reserved_paise
    if available >= paise:
        return
    settings = get_settings()
    if settings.app_env != "development":
        raise ValueError("Insufficient credits")
    need = max(paise * 5, 5000) - available
    if need > 0:
        top_up(db, workspace_id, need, reference=f"dev-auto-topup-{uuid4()}")


def reserve_for_call(db: Session, workspace_id: UUID, paise: int, call_ref: str) -> None:
    ensure_call_credits(db, workspace_id, paise)
    account = ensure_wallet(db, workspace_id)
    available = account.balance_paise - account.reserved_paise
    if available < paise:
        raise ValueError("Insufficient credits")
    account.reserved_paise += paise
    db.add(
        WalletLedgerEntry(
            workspace_id=workspace_id,
            entry_type=LedgerEntryType.reserve,
            amount_paise=paise,
            reference=f"reserve-{call_ref}",
            meta={"call_ref": call_ref},
        )
    )
    db.commit()


def release_reserve(db: Session, workspace_id: UUID, reserved_paise: int, call_ref: str) -> None:
    account = ensure_wallet(db, workspace_id)
    account.reserved_paise = max(0, account.reserved_paise - reserved_paise)
    db.add(
        WalletLedgerEntry(
            workspace_id=workspace_id,
            entry_type=LedgerEntryType.release,
            amount_paise=reserved_paise,
            reference=f"release-{call_ref}",
            meta={"call_ref": call_ref, "reason": "call_failed"},
        )
    )
    db.commit()


def settle_call(db: Session, workspace_id: UUID, reserved_paise: int, actual_paise: int, call_ref: str) -> None:
    account = ensure_wallet(db, workspace_id)
    account.reserved_paise = max(0, account.reserved_paise - reserved_paise)
    account.balance_paise -= actual_paise
    release = reserved_paise - actual_paise
    if release > 0:
        db.add(
            WalletLedgerEntry(
                workspace_id=workspace_id,
                entry_type=LedgerEntryType.release,
                amount_paise=release,
                reference=f"release-{call_ref}",
                meta={},
            )
        )
    db.add(
        WalletLedgerEntry(
            workspace_id=workspace_id,
            entry_type=LedgerEntryType.debit,
            amount_paise=actual_paise,
            reference=f"settle-{call_ref}",
            meta={"call_ref": call_ref},
        )
    )
    db.commit()