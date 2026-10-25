"""Investment account validation and canonical cash aggregation."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..models import SyncChange, UserAccountProjection


def get_investment_account(db: Session, *, user_id: str, account_id: str):
    return db.scalar(select(UserAccountProjection).where(
        UserAccountProjection.user_id == user_id, UserAccountProjection.sync_id == account_id,
        UserAccountProjection.account_type == 'investment'))


def _deleted_ledger_ids(db: Session, ledger_ids: set[str]) -> set[str]:
    if not ledger_ids:
        return set()
    ranked = select(SyncChange.ledger_id, SyncChange.action, func.row_number().over(
        partition_by=SyncChange.ledger_id, order_by=SyncChange.change_id.desc()).label('rn')).where(
        SyncChange.ledger_id.in_(ledger_ids), SyncChange.entity_type == 'ledger_snapshot').subquery()
    return {str(r[0]) for r in db.execute(select(ranked.c.ledger_id).where(
        ranked.c.rn == 1, ranked.c.action == 'delete')).all()}


def investment_account_cash_balances(db: Session, *, user_id: str) -> dict[str, dict[str, object]]:
    from .finance import account_balances
    balances = account_balances(db, user_id=user_id)
    ids = set(db.scalars(select(UserAccountProjection.sync_id).where(
        UserAccountProjection.user_id == user_id,
        UserAccountProjection.account_type == 'investment')).all())
    return {key: value for key, value in balances.items() if key in ids}
