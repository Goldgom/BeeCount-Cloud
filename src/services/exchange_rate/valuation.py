"""Auditable conversion graph. Overrides: 1 quote = rate base; cache: 1 base = rate quote.

USDT is an independent currency, never an implicit USD peg. Only configured
user projections or sourced provider observations can connect currencies.
"""
from __future__ import annotations
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...models import ExchangeRateCache, UserExchangeRateProjection
from ...config import get_settings
from . import fetcher


def iso(value):
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


class ConversionGraph:
    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.edges = {}
        self.attempted = set()
        # Newest duplicate business pair wins deterministically.
        overrides = db.scalars(select(UserExchangeRateProjection).where(
            UserExchangeRateProjection.user_id == user_id).order_by(
            UserExchangeRateProjection.source_change_id.desc(),
            UserExchangeRateProjection.updated_at.desc(), UserExchangeRateProjection.sync_id.desc())).all()
        for row in overrides:
            self.add(row.quote_currency, row.base_currency, row.rate,
                     'user_override:' + row.sync_id, iso(row.updated_at)[:10], iso(row.updated_at), False)
        self.load_cache()

    def add(self, source, target, rate, origin, date, fetched, stale):
        try:
            rate = Decimal(str(rate))
        except (InvalidOperation, ValueError):
            return
        if not rate.is_finite() or rate <= 0:
            return
        source, target = source.upper(), target.upper()
        for a, b, r in ((source, target, rate), (target, source, 1 / rate)):
            self.edges.setdefault(a, {}).setdefault(b, dict(from_currency=a, to_currency=b,
                rate=str(r), source=origin, rate_date=date, fetched_at=fetched, stale=stale))

    def load_cache(self):
        ttl = get_settings().exchange_rate_cache_ttl_hours * 3600
        now = datetime.now(timezone.utc)
        for row in self.db.scalars(select(ExchangeRateCache)).all():
            fetched = row.fetched_at.replace(tzinfo=timezone.utc) if row.fetched_at.tzinfo is None else row.fetched_at
            for target, rate in row.payload_json.items():
                self.add(row.base_currency, target, rate, row.source, row.rate_date,
                         iso(row.fetched_at), (now - fetched).total_seconds() > ttl)

    def find(self, source, target):
        source, target = source.upper(), target.upper()
        queue = deque([(source, Decimal(1), [])])
        seen = {source}
        while queue:
            current, rate, path = queue.popleft()
            if current == target:
                return dict(status='identity' if not path else 'converted', rate=str(rate), path=path,
                            stale=any(step['stale'] for step in path))
            for nxt, edge in self.edges.get(current, {}).items():
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, rate * Decimal(edge['rate']), path + [edge]))
        return None

    async def resolve(self, source, target):
        found = self.find(source, target)
        if found:
            return found
        if get_settings().exchange_rate_proxy_enabled:
            for base in (target.upper(), source.upper()):
                if base not in self.attempted:
                    self.attempted.add(base)
                    try:
                        await fetcher.get_rates(self.db, base)
                        self.load_cache()
                    except Exception:
                        pass
                found = self.find(source, target)
                if found:
                    return found
        return dict(status='missing_rate', rate=None, path=[], stale=False)


def converted(amount, fx):
    if amount is None or fx['rate'] is None:
        return None
    return float(Decimal(str(amount)) * Decimal(fx['rate']))
