"""Append-only financial operations. All money is Decimal in the journal.

Events are cloud-only, not fake mobile income/expense transactions. REST and
MCP share this implementation and the same per-user transactional write lock.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from ..models import User, UserAccountProjection, Ledger, LedgerMember, ReadTxProjection
from ..models_finance import FinanceEvent


def fail(message: str, code: int = 422):
    raise HTTPException(code, message)


def money(value) -> Decimal:
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) > Decimal('1e18'):
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError):
        fail('Invalid finite money amount')


def instant(value=None) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        if result is None:
            result = datetime.now(timezone.utc)
        if not isinstance(result, datetime):
            fail('Timestamp must be an ISO string')
        if result.tzinfo is None:
            fail('Timestamp must include timezone')
        return result.astimezone(timezone.utc)
    except ValueError:
        fail('Invalid timestamp')


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def events(db, user_id):
    return db.scalars(select(FinanceEvent).where(FinanceEvent.user_id == user_id)
                      .order_by(FinanceEvent.effective_at, FinanceEvent.created_at, FinanceEvent.id)).all()


def account_balances(db: Session, *, user_id: str, as_of=None) -> dict:
    from .investment_accounts import _deleted_ledger_ids
    at = instant(as_of)
    accounts = db.scalars(select(UserAccountProjection).where(UserAccountProjection.user_id == user_id)).all()
    totals = {a.sync_id: money(a.initial_balance or 0) for a in accounts}
    ledger_ids = set(db.scalars(select(Ledger.id).join(LedgerMember, LedgerMember.ledger_id == Ledger.id)
                                .where(LedgerMember.user_id == user_id)).all())
    ledger_ids -= _deleted_ledger_ids(db, ledger_ids)
    txs = db.scalars(select(ReadTxProjection).where(ReadTxProjection.ledger_id.in_(ledger_ids),
                                                  ReadTxProjection.happened_at <= at)).all() if ledger_ids else []
    names = {}
    for a in accounts:
        names.setdefault(a.name, []).append(a.sync_id)
    def resolve(aid, name):
        if aid:
            return aid
        candidates = names.get(name, [])
        return candidates[0] if len(candidates) == 1 else None
    for tx in txs:
        # amount is original/account currency; native_amount is ledger base only
        # (SYNC_ARCHITECTURE §4.5). Never apply native_amount to account balances.
        amount = money(tx.amount or 0)
        aid = resolve(tx.account_sync_id, tx.account_name)
        source = resolve(tx.from_account_sync_id, tx.from_account_name)
        target = resolve(tx.to_account_sync_id, tx.to_account_name)
        if tx.tx_type in ('income', 'expense', 'adjustment') and aid in totals:
            totals[aid] += -amount if tx.tx_type == 'expense' else amount
        elif tx.tx_type == 'transfer':
            if source in totals:
                totals[source] -= amount
            if target in totals:
                totals[target] += amount
    for event in events(db, user_id):
        if utc(event.effective_at) <= at:
            for account_id, delta in event.effects.items():
                if account_id in totals:
                    totals[account_id] += money(delta)
    return {a.sync_id: {'account_id': a.sync_id, 'account_name': a.name or '',
                       'currency': (a.currency or 'CNY').upper(), 'cash_balance': float(totals[a.sync_id]),
                       'balance_decimal': str(totals[a.sync_id]), 'cash_as_of': at.isoformat(),
                       'balance_source': 'projection_plus_finance_events'} for a in accounts}


def output(row):
    return {'id': row.id, 'kind': row.kind, 'effective_at': utc(row.effective_at).isoformat(),
            'created_at': utc(row.created_at).isoformat(), 'payload': row.payload, 'effects': row.effects}


def execute(db: Session, *, user_id: str, kind: str, key: str, data: dict) -> dict:
    """One atomic operation; callers own commit/rollback. No external side effects."""
    if not key or len(key) > 255:
        fail('Idempotency-Key required (1..255 characters)')
    digest = hashlib.sha256(json.dumps([kind, data], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    # UPDATE locks the user row on PostgreSQL, and the write transaction on SQLite.
    # Includes receipt lookup so concurrent same-key requests cannot double apply.
    db.execute(update(User).where(User.id == user_id).values(email=User.email))
    prior = db.scalar(select(FinanceEvent).where(FinanceEvent.user_id == user_id, FinanceEvent.request_key == key))
    if prior:
        if prior.request_hash != digest:
            fail('Idempotency key reused with different payload', 409)
        return output(prior)
    at = instant(data.get('effective_at'))
    if at > datetime.now(timezone.utc):
        fail('Future effective_at is not supported')
    journal = events(db, user_id)
    balances = account_balances(db, user_id=user_id, as_of=at)
    effects, payload = {}, dict(data)

    def account(account_id, currency=None):
        if account_id not in balances:
            fail('Account not found or not owned', 404)
        if currency is not None and not isinstance(currency, str):
            fail('Currency must be a string')
        if currency and currency.upper() != balances[account_id]['currency']:
            fail('Account currency mismatch')
        return balances[account_id]

    def positive(value):
        amount = money(value)
        if amount <= 0:
            fail('Amount must be positive')
        return amount

    def reference(event_id, expected_kind):
        row = next((e for e in journal if e.id == event_id and e.kind == expected_kind), None)
        if not row:
            fail('Referenced event not found', 404)
        return row

    def require_text(field):
        if not isinstance(data.get(field), str) or not data[field].strip():
            fail(f'{field} is required')

    if kind == 'reconciliation':
        for field in ('account_id', 'source', 'reason', 'effective_at'):
            require_text(field)
        aid = data['account_id']
        before = money(account(aid)['balance_decimal'])
        if 'expected_balance' not in data:
            fail('expected_balance required for conflict detection')
        if money(data['expected_balance']) != before:
            fail('Balance changed; reload and reconcile again', 409)
        # Inserting an earlier calibration would invalidate later observations.
        if any(e.kind == kind and aid in e.effects and utc(e.effective_at) >= at for e in journal):
            fail('Later reconciliation exists', 409)
        classification = data.get('difference_classification', 'unknown')
        if classification not in ('missing_income', 'missing_expense', 'unknown'):
            fail('Unsupported difference_classification')
        payload['difference_classification'] = classification
        after = money(data.get('target_balance'))
        effects[aid] = str(after - before)
        payload.update(before_balance=str(before), after_balance=str(after), difference=str(after-before),
                       currency=balances[aid]['currency'])
    elif kind == 'transfer':
        source, target = data.get('from_account_id'), data.get('to_account_id')
        if source == target:
            fail('Transfer accounts must differ')
        account(source, data.get('from_currency'))
        account(target, data.get('to_currency'))
        for field in ('from_currency', 'to_currency', 'external_id', 'source'):
            require_text(field)
        if any(e.kind == kind and e.payload.get('external_id') == data['external_id']
               and e.payload.get('source') == data['source'] for e in journal):
            fail('External transfer already recorded', 409)
        debit, credit = positive(data.get('from_amount')), positive(data.get('to_amount'))
        effects = {source: str(-debit), target: str(credit)}
        fee = money(data.get('fee_amount', 0))
        if fee < 0:
            fail('Fee cannot be negative')
        if fee:
            fee_account = data.get('fee_account_id')
            account(fee_account, data.get('fee_currency'))
            require_text('fee_currency')
            effects[fee_account] = str(money(effects.get(fee_account, 0)) - fee)
        payload.update(from_amount=str(debit), to_amount=str(credit), fee_amount=str(fee),
                       actual_exchange_rate=str(credit/debit))
    elif kind == 'receivable':
        for field in ('counterparty', 'currency', 'reason'):
            require_text(field)
        payload['amount'] = str(positive(data.get('amount')))
        # Recognition is not cash income; no account effects.
    elif kind in ('receivable_installment', 'repayment'):
        parent = reference(data.get('receivable_id'), 'receivable')
        if at < utc(parent.effective_at):
            fail('Payment/schedule predates receivable')
        amount = positive(data.get('amount'))
        related = [e for e in journal if e.kind == kind and e.payload.get('receivable_id') == parent.id]
        total = sum((money(e.payload['amount']) for e in related), Decimal(0))
        if total + amount > money(parent.payload['amount']):
            fail('Amount exceeds remaining receivable', 409)
        payload.update(amount=str(amount), currency=parent.payload['currency'])
        if kind == 'receivable_installment':
            require_text('due_at')
            instant(data['due_at'])
        else:
            aid = data.get('account_id')
            account(aid, parent.payload['currency'])
            installment_id = data.get('installment_id')
            if installment_id:
                installment = reference(installment_id, 'receivable_installment')
                if installment.payload['receivable_id'] != parent.id:
                    fail('Installment belongs to another receivable')
                paid = sum((money(e.payload['amount']) for e in related if e.payload.get('installment_id') == installment_id), Decimal(0))
                if paid + amount > money(installment.payload['amount']):
                    fail('Amount exceeds installment remaining', 409)
            effects[aid] = str(amount)
    elif kind == 'reversal':
        require_text('reason')
        original = next((e for e in journal if e.id == data.get('event_id')), None)
        if not original or original.kind not in ('reconciliation', 'transfer'):
            fail('Only reconciliation/transfer can be reversed', 422)
        if any(e.kind == 'reversal' and e.payload.get('event_id') == original.id for e in journal):
            fail('Already reversed', 409)
        if at < utc(original.effective_at):
            fail('Reversal predates original event')
        if any(e.kind == 'reconciliation' and e.id != original.id and set(e.effects) & set(original.effects)
               and utc(e.effective_at) >= utc(original.effective_at) for e in journal):
            fail('Later reconciliation exists; reverse it first', 409)
        effects = {aid: str(-money(delta)) for aid, delta in original.effects.items()}
    elif kind == 'investment_event':
        allowed = {'subscription', 'redemption', 'dividend_cash', 'dividend_reinvested', 'fee', 'tax',
                   'valuation_change', 'transfer_in', 'transfer_out', 'buy', 'sell', 'interest',
                   'funding_fee', 'realized_pnl'}
        if data.get('classification') not in allowed:
            fail('Unsupported investment event classification')
        for field in ('account_id', 'currency', 'source', 'reason'):
            require_text(field)
        account(data['account_id'], data['currency'])
        payload['amount'] = str(money(data.get('amount')) if data['classification'] in
                                ('valuation_change', 'realized_pnl', 'funding_fee') else positive(data.get('amount')))
        # Investment annotations classify evidence; no synthetic cash posting.
    elif kind == 'snapshot':
        day = at.date().isoformat()
        existing = next((e for e in journal if e.kind == 'snapshot' and e.payload['day'] == day), None)
        if existing:
            fail('Daily snapshot already captured; immutable', 409)
        from ..models import InvestmentProduct
        holdings = db.scalars(select(InvestmentProduct).where(InvestmentProduct.user_id == user_id)).all()
        captured = []
        for p in holdings:
            mode = 'money_fund' if p.is_money_fund else getattr(p, 'valuation_mode', None) or 'shares_nav'
            value = getattr(p, 'snapshot_amount', None) if mode == 'amount_snapshot' else (
                p.quantity if mode == 'money_fund' or p.is_money_fund else
                0 if p.quantity == 0 else p.quantity * p.current_price if p.current_price is not None else None)
            captured.append({'id': p.id, 'account_id': p.account_id, 'currency': p.currency,
                             'value': value, 'cost_basis_total': p.quantity * p.cost_basis if p.cost_basis is not None else None,
                             'valuation_mode': mode, 'valuation_source': getattr(p, 'valuation_source', None),
                             'snapshot_at': getattr(p, 'snapshot_at', None).isoformat() if getattr(p, 'snapshot_at', None) else None,
                             'price_as_of': p.price_updated_at.isoformat() if p.price_updated_at else None})
        # We cannot reconstruct past holdings from mutable products. Capture now only.
        if at.date() != datetime.now(timezone.utc).date() or abs((datetime.now(timezone.utc)-at).total_seconds()) > 300:
            fail('Snapshot capture must be current (within 5 minutes); historical backfill is not supported')
        payload = {'day': day, 'accounts': balances, 'holdings': captured, 'trigger': data.get('trigger', 'manual'),
                   'historical_projection_caveat': 'Captured observation; later projection edits do not rewrite this snapshot'}
    else:
        fail('Unsupported operation')
    # Historical postings must not silently invalidate a later calibration.
    if kind not in ('reconciliation', 'reversal') and effects and any(
            e.kind == 'reconciliation' and set(e.effects) & set(effects) and utc(e.effective_at) >= at for e in journal):
        fail('Posting predates a reconciliation; reverse/reconcile explicitly', 409)
    row = FinanceEvent(id=str(uuid4()), user_id=user_id, request_key=key, request_hash=digest,
                       kind=kind, effective_at=at, payload=payload, effects=effects)
    db.add(row)
    db.flush()
    return output(row)


def receivables(db, user_id):
    journal = events(db, user_id)
    result = []
    for item in journal:
        if item.kind != 'receivable':
            continue
        repayments = [output(e) for e in journal if e.kind == 'repayment' and e.payload.get('receivable_id') == item.id]
        installments = [output(e) for e in journal if e.kind == 'receivable_installment' and e.payload.get('receivable_id') == item.id]
        paid = sum((money(e['payload']['amount']) for e in repayments), Decimal(0))
        for installment in installments:
            part_paid = sum((money(e['payload']['amount']) for e in repayments if e['payload'].get('installment_id') == installment['id']), Decimal(0))
            installment.update(paid=str(part_paid), remaining=str(money(installment['payload']['amount'])-part_paid))
        result.append({**output(item), 'paid': str(paid), 'remaining': str(money(item.payload['amount'])-paid),
                       'installments': installments, 'repayments': repayments})
    return result


def period_report(db, user_id, start, end):
    start, end = instant(start), instant(end)
    if start >= end:
        fail('start must precede end')
    journal = events(db, user_id)
    selected = [output(e) for e in journal if start < utc(e.effective_at) <= end and e.kind != 'snapshot']
    snapshots = [e for e in journal if e.kind == 'snapshot']
    def boundary(at):
        return next((e for e in reversed(snapshots) if utc(e.effective_at) == at), None)
    opening, closing = boundary(start), boundary(end)
    def totals(snapshot):
        if not snapshot:
            return None
        result = {}
        for a in snapshot.payload['accounts'].values():
            cur = a['currency']; result[cur] = result.get(cur, Decimal(0)) + money(a['balance_decimal'])
        for p in snapshot.payload['holdings']:
            cur = p['currency']
            if p['value'] is None:
                result[cur] = None
            elif result.get(cur, 0) is not None:
                result[cur] = result.get(cur, Decimal(0)) + money(p['value'])
        return {c: str(v) if v is not None else None for c,v in result.items()}
    a, b = totals(opening), totals(closing)
    delta = {c: str(money(b[c])-money(a[c])) if a.get(c) is not None and b.get(c) is not None else None
             for c in set(a or {}) | set(b or {})} if a is not None and b is not None else None
    return {'start': start.isoformat(), 'end': end.isoformat(), 'opening_assets': a, 'closing_assets': b,
            'asset_change': delta, 'investment_return': None, 'return_rate': None,
            'reason': 'Asset change is not investment return; complete priced positions and cashflow coverage are not established',
            'events': selected, 'snapshot_boundary_policy': 'Exact captured timestamps only; no fabricated historical valuations'}
