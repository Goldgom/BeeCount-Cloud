"""Investment-account validation and cash-balance aggregation.

Holdings are user-owned but must point to an ``investment`` account.  Account
cash follows the same initial-balance/income/expense/transfer formula as the
workspace account view; holdings are added separately by callers.
"""
from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import Ledger, LedgerMember, ReadTxProjection, SyncChange, UserAccountProjection


def get_investment_account(db: Session, *, user_id: str, account_id: str) -> UserAccountProjection | None:
    return db.scalar(
        select(UserAccountProjection).where(
            UserAccountProjection.user_id == user_id,
            UserAccountProjection.sync_id == account_id,
            UserAccountProjection.account_type == "investment",
        )
    )


def _deleted_ledger_ids(db: Session, ledger_ids: set[str]) -> set[str]:
    """Local soft-delete check, kept here to avoid a service-to-router import."""
    if not ledger_ids:
        return set()
    ranked = select(
        SyncChange.ledger_id,
        SyncChange.action,
        func.row_number().over(
            partition_by=SyncChange.ledger_id,
            order_by=SyncChange.change_id.desc(),
        ).label("rn"),
    ).where(
        SyncChange.ledger_id.in_(ledger_ids),
        SyncChange.entity_type == "ledger_snapshot",
    ).subquery()
    return {
        str(row[0]) for row in db.execute(
            select(ranked.c.ledger_id).where(ranked.c.rn == 1, ranked.c.action == "delete")
        ).all()
    }


def investment_account_cash_balances(db: Session, *, user_id: str) -> dict[str, dict[str, object]]:
    """Return current cash balances keyed by investment-account sync id."""
    accounts = db.scalars(
        select(UserAccountProjection).where(
            UserAccountProjection.user_id == user_id,
            UserAccountProjection.account_type == "investment",
        )
    ).all()
    balances: dict[str, dict[str, object]] = {
        row.sync_id: {
            "account_id": row.sync_id,
            "account_name": row.name or "",
            "currency": (row.currency or "CNY").upper(),
            "cash_balance": float(row.initial_balance or 0),
        }
        for row in accounts
    }
    if not balances:
        return balances

    # Match the workspace view: shared-ledger transactions count when the user
    # is a member, even if another user originally created the ledger.
    ledger_ids = {
        row.id for row in db.scalars(
            select(Ledger).join(LedgerMember, LedgerMember.ledger_id == Ledger.id)
            .where(LedgerMember.user_id == user_id)
        ).all()
    }
    ledger_ids -= _deleted_ledger_ids(db, ledger_ids)
    if not ledger_ids:
        return balances

    main_rows = db.execute(
        select(
            ReadTxProjection.account_sync_id,
            func.coalesce(func.sum(case(
                (ReadTxProjection.tx_type == "income", ReadTxProjection.amount),
                (ReadTxProjection.tx_type == "expense", -ReadTxProjection.amount),
                else_=0.0,
            )), 0.0),
        ).where(
            ReadTxProjection.ledger_id.in_(ledger_ids),
            ReadTxProjection.account_sync_id.in_(balances),
            ReadTxProjection.tx_type.in_(("income", "expense")),
        ).group_by(ReadTxProjection.account_sync_id)
    ).all()
    from_rows = db.execute(
        select(ReadTxProjection.from_account_sync_id, func.coalesce(func.sum(ReadTxProjection.amount), 0.0)).where(
            ReadTxProjection.ledger_id.in_(ledger_ids),
            ReadTxProjection.from_account_sync_id.in_(balances),
            ReadTxProjection.tx_type == "transfer",
        ).group_by(ReadTxProjection.from_account_sync_id)
    ).all()
    to_rows = db.execute(
        select(ReadTxProjection.to_account_sync_id, func.coalesce(func.sum(ReadTxProjection.amount), 0.0)).where(
            ReadTxProjection.ledger_id.in_(ledger_ids),
            ReadTxProjection.to_account_sync_id.in_(balances),
            ReadTxProjection.tx_type == "transfer",
        ).group_by(ReadTxProjection.to_account_sync_id)
    ).all()
    for account_id, amount in main_rows:
        balances[account_id]["cash_balance"] = float(balances[account_id]["cash_balance"]) + float(amount)
    for account_id, amount in from_rows:
        balances[account_id]["cash_balance"] = float(balances[account_id]["cash_balance"]) - float(amount)
    for account_id, amount in to_rows:
        balances[account_id]["cash_balance"] = float(balances[account_id]["cash_balance"]) + float(amount)
    return balances
