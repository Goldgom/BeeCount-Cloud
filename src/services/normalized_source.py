"""Versioned external CLI/export bridge. Data only: never execute commands."""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from ..models_data_sources import DataSource, DataSourceEvent, DataSourceSyncReceipt
from . import data_sources as service
from .binance_source import MODULES


class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid')


def decimal_string(value):
    if value is None:
        return value
    if not isinstance(value,str) or len(value)>100:
        raise ValueError('Amounts must be finite decimal strings')
    try:
        number=Decimal(value)
        if not number.is_finite() or abs(number)>Decimal('1e30'):
            raise ValueError()
    except (InvalidOperation,ValueError):
        raise ValueError('Amounts must be finite bounded decimal strings') from None
    return value


class Coverage(StrictModel):
    id: Literal['spot','funding','earn_flexible','portfolio_margin','usd_m_futures','coin_m_futures']
    status: Literal['ok','unknown']
    error: str | None=Field(default=None,max_length=120)


class Balance(StrictModel):
    module: Literal['spot','funding','earn_flexible','portfolio_margin','usd_m_futures','coin_m_futures']
    asset: str=Field(pattern=r'^[A-Z0-9]{1,30}$')
    balance: str
    net_equity: str | None=None
    available: str | None=None
    unrealized_pnl: str | None=None
    value_usdt: str | None=None
    included_in_pm_equity: bool=False
    _amounts=field_validator('balance','net_equity','available','unrealized_pnl','value_usdt',mode='before')(decimal_string)


class Position(StrictModel):
    module: Literal['spot','funding','earn_flexible','portfolio_margin','usd_m_futures','coin_m_futures']
    symbol: str=Field(pattern=r'^[A-Z0-9_]{1,50}$')
    quantity: str
    notional: str | None=None
    unrealized_pnl: str | None=None
    included_in_equity: Literal[True]=True
    _amounts=field_validator('quantity','notional','unrealized_pnl',mode='before')(decimal_string)


class Event(StrictModel):
    kind: str=Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9_:-]+$')
    external_id: str=Field(min_length=1,max_length=255)
    payload: dict=Field(default_factory=dict)


class PMEquity(StrictModel):
    currency: Literal['USD']='USD'
    amount: str
    _amount=field_validator('amount',mode='before')(decimal_string)


class ImportSnapshot(StrictModel):
    schema_version: Literal[1]
    source_time: datetime
    modules: list[Coverage]=Field(max_length=6)
    balances: list[Balance]=Field(default_factory=list,max_length=10000)
    positions: list[Position]=Field(default_factory=list,max_length=10000)
    events: list[Event]=Field(default_factory=list,max_length=10000)
    pm_equity: PMEquity | None=None

    @field_validator('source_time')
    @classmethod
    def aware_timestamp(cls,value):
        if value.tzinfo is None or value.timestamp()>service.now().timestamp()+300:
            raise ValueError('Source time must include timezone and not be in the future')
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def coverage_consistent(self):
        states={m.id:m.status for m in self.modules}
        if len(states)!=len(self.modules):
            raise ValueError('Duplicate modules are not allowed')
        if any(states.get(b.module)!='ok' for b in self.balances+self.positions):
            raise ValueError('Balances and positions require explicit ok module coverage')
        if states.get('portfolio_margin')=='ok' and self.pm_equity is None:
            raise ValueError('Successful PM coverage requires authoritative PM equity')
        if self.pm_equity is not None and states.get('portfolio_margin')!='ok':
            raise ValueError('PM equity requires explicit PM coverage')
        if self.pm_equity is not None and any(b.module in ('usd_m_futures','coin_m_futures') or (b.module=='portfolio_margin' and not b.included_in_pm_equity) for b in self.balances):
            raise ValueError('PM equity must not double count derivative or PM balances')
        if any(b.included_in_pm_equity and (b.module!='portfolio_margin' or self.pm_equity is None) for b in self.balances):
            raise ValueError('Included PM balances require PM equity')
        return self


def ingest(db,user_id,source_id,body,key=None):
    row=service.owned(db,user_id,source_id)
    if row.provider!='normalized_json':
        raise HTTPException(422,'Only normalized_json accepts imported snapshots')
    if row.paused:
        raise HTTPException(409,'Resume this source before importing')
    if key is not None and not 1<=len(key)<=128:
        raise HTTPException(422,'Idempotency-Key length must be 1..128')
    canonical=json.dumps(body.model_dump(mode='json'),sort_keys=True,separators=(',',':'))
    if len(canonical.encode())>2*1024*1024:
        raise HTTPException(413,'Import exceeds 2 MiB')
    # Tenant row write serializes imports/config changes on SQLite and PostgreSQL.
    from ..models import User
    db.execute(update(User).where(User.id==user_id).values(id=user_id))
    db.refresh(row)
    if row.paused:
        raise HTTPException(409,'Resume this source before importing')
    digest=hashlib.sha256(canonical.encode()).hexdigest()
    prefix='ingest:'+hashlib.sha256((key or canonical).encode()).hexdigest()[:32]+':'
    receipt_key=prefix+digest
    existing=db.scalar(select(DataSourceSyncReceipt.request_key).where(DataSourceSyncReceipt.source_id==source_id,
            DataSourceSyncReceipt.request_key.startswith(prefix)))
    if existing:
        if existing!=receipt_key:
            raise HTTPException(409,'Idempotency key reused with different payload')
        return service.serialize(db,row)
    if row.snapshot and row.snapshot.get('source_time'):
        previous_time=datetime.fromisoformat(row.snapshot['source_time'])
        if body.source_time < previous_time:
            raise HTTPException(409,'Import is older than the current observation')
        if body.source_time == previous_time:
            if row.snapshot.get('import_payload_sha256')==digest:
                return service.serialize(db,row)
            raise HTTPException(409,'Conflicting payload for the same observation time')
    # Validate all event identities before mutating either snapshot or event store.
    incoming={}
    for event in body.events:
        identity=(event.kind,event.external_id)
        if identity in incoming and incoming[identity].payload!=event.payload:
            raise HTTPException(409,'Conflicting payload for duplicate event identity')
        incoming[identity]=event
    new_events=[]
    for (kind,external_id),event in incoming.items():
        previous=db.scalar(select(DataSourceEvent).where(DataSourceEvent.source_id==source_id,
            DataSourceEvent.kind==kind,DataSourceEvent.external_id==external_id))
        if previous:
            if previous.payload!=event.payload:
                raise HTTPException(409,'Existing event identity has different payload')
        else:
            new_events.append(event)
    stamp=body.source_time.isoformat()
    modules={m.id:dict(m.model_dump(),source_time=stamp if m.status=='ok' else None) for m in body.modules}
    for module in MODULES:
        modules.setdefault(module,dict(id=module,status='unknown',error='not_provided',source_time=None))
    balances=[dict(b.model_dump(),source_time=stamp) for b in body.balances]
    vals=[Decimal(b.value_usdt) for b in body.balances if b.value_usdt is not None and not b.included_in_pm_equity]
    complete=all(m['status']=='ok' for m in modules.values()) and all(b.value_usdt is not None for b in body.balances)
    row.snapshot=dict(import_payload_sha256=digest,modules=list(modules.values()),balances=balances,
        positions=[dict(p.model_dump(),source_time=stamp) for p in body.positions],
        source_time=stamp,observed_at=service.now().isoformat(),source_time_status='external_reported_observation',
        valuation_date=stamp[:10],valuation_currency='USDT',
        known_net_equity=str(sum(vals,Decimal(0))),net_equity=str(sum(vals,Decimal(0))) if complete and body.pm_equity is None else None,
        pm_equity=dict(body.pm_equity.model_dump(),source_time=stamp) if body.pm_equity else None,
        history_coverage=[dict(id='imported_events',status='unknown',error='external_export_not_full_history')])
    for event in new_events:
        db.add(DataSourceEvent(source_id=source_id,**event.model_dump()))
    row.status='ok' if complete else 'partial'
    row.last_attempt_at=service.now()
    # Staleness follows the actual external observation, NOT upload time.
    row.last_success_at=body.source_time
    row.error=None
    db.add(DataSourceSyncReceipt(source_id=source_id,request_key=receipt_key))
    db.commit()
    return service.serialize(db,row)
