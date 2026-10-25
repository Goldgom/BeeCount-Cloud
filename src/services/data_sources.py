"""Tenant-owned source lifecycle, encrypted secrets and fenced database sync leases."""
import asyncio
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select, update, delete, or_, func
from ..config import get_settings
from ..models import UserAccountProjection
from ..models_data_sources import DataSource, DataSourceEvent, DataSourceSyncReceipt
from .binance_source import BinanceAdapter, MODULES, SourceError


def now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def iso(value):
    return utc(value).isoformat() if value else None


def cipher():
    # Domain-separated stable deployment key; JWT key rotation requires re-entering credentials.
    secret = get_settings().jwt_secret
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('beecount:data-sources:v1:'+secret).encode()).digest()))


def encrypt(credentials):
    return cipher().encrypt(json.dumps(credentials).encode()).decode()


def owned(db, user_id, source_id):
    row = db.scalar(select(DataSource).where(DataSource.id==source_id,DataSource.user_id==user_id))
    if not row:
        raise HTTPException(404,'Data source not found')
    return row


def serialize(db, row):
    age = (now()-utc(row.last_success_at)).total_seconds() if row.last_success_at else None
    snapshot = row.snapshot or {}
    return dict(snapshot, id=row.id,name=row.name,provider=row.provider,account_id=row.account_id,
        coverage_policy=row.coverage_policy,poll_interval_seconds=row.poll_interval_seconds,paused=row.paused,
        symbols=row.symbols,status=row.status,error=row.error,credentials_configured=bool(row.credentials_encrypted),
        last_attempt_at=iso(row.last_attempt_at),last_success_at=iso(row.last_success_at),next_sync_at=iso(row.next_sync_at),
        stale=age is None or age>row.poll_interval_seconds*2,
        modules=snapshot.get('modules',[dict(id=m,status='unknown',error='not_synced',source_time=None) for m in MODULES]),
        balances=snapshot.get('balances',[]),positions=snapshot.get('positions',[]),
        event_count=db.scalar(select(func.count()).select_from(DataSourceEvent).where(DataSourceEvent.source_id==row.id)),
        sync_in_progress=bool(row.lock_until and utc(row.lock_until)>now()))


def validate_binding(db, user_id, data, source_id=None):
    account_id = data.get('account_id')
    policy = data.get('coverage_policy','separate')
    if policy=='replace_bound_account':
        if not account_id or not db.scalar(select(UserAccountProjection).where(
                UserAccountProjection.user_id==user_id,UserAccountProjection.sync_id==account_id)):
            raise HTTPException(422,'Binding requires an account owned by this user')
        # Serialize binding decisions on user row (also SQLite write transaction).
        from ..models import User
        db.execute(update(User).where(User.id==user_id).values(id=user_id))
        conflict = select(DataSource.id).where(DataSource.user_id==user_id,DataSource.account_id==account_id,
            DataSource.coverage_policy=='replace_bound_account')
        if source_id:
            conflict = conflict.where(DataSource.id!=source_id)
        if db.scalar(conflict):
            raise HTTPException(409,'Account is already covered by another source')
    elif account_id:
        raise HTTPException(422,'Separate source must not bind an account')


async def synchronize(db, user_id, source_id, key=None, client=None):
    row = owned(db,user_id,source_id)
    if row.provider != 'binance_api':
        raise HTTPException(422, 'This provider accepts explicit JSON ingestion only; no server-side command or REST polling')
    if key and db.scalar(select(DataSourceSyncReceipt.id).where(
            DataSourceSyncReceipt.source_id==source_id,DataSourceSyncReceipt.request_key==key)):
        return serialize(db,row)
    token, at = str(uuid4()), now()
    acquired = db.execute(update(DataSource).where(DataSource.id==source_id,DataSource.user_id==user_id,
        or_(DataSource.lock_until.is_(None),DataSource.lock_until<at)).values(
            lock_token=token,lock_until=at+timedelta(minutes=15),last_attempt_at=at).execution_options(synchronize_session=False))
    db.commit()
    if acquired.rowcount!=1:
        raise HTTPException(409,'Source sync already in progress')
    db.refresh(row)
    try:
        credentials = json.loads(cipher().decrypt(row.credentials_encrypted.encode()))
        result, events, cursors = await asyncio.wait_for(
            BinanceAdapter(credentials,client=client).collect(row.symbols,row.cursors),timeout=600)
        # Recheck fence after network; deletion/config mutation cannot resurrect a source.
        db.expire_all()
        row = db.scalar(select(DataSource).where(DataSource.id==source_id,DataSource.user_id==user_id,DataSource.lock_token==token))
        if row is None:
            raise HTTPException(409,'Source changed during sync')
        for event in events:
            if not db.scalar(select(DataSourceEvent.id).where(DataSourceEvent.source_id==source_id,
                    DataSourceEvent.kind==event['kind'],DataSourceEvent.external_id==event['external_id'])):
                db.add(DataSourceEvent(source_id=source_id,**event))
        row.snapshot, row.cursors = result, cursors
        success = any(m['status']=='ok' for m in result['modules'])
        row.status = ('ok' if all(m['status']=='ok' for m in result['modules']) else 'partial') if success else 'error'
        row.error = None if success else 'all_modules_unknown'
        if success:
            row.last_success_at=now()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        row=owned(db,user_id,source_id)
        if row.lock_token!=token:
            raise HTTPException(409,'Source changed during sync')
        row.status='error'
        row.error=str(exc) if isinstance(exc,SourceError) else 'sync_failed'  # no exception repr / logs
    row.lock_token=None
    row.lock_until=None
    row.next_sync_at=now()+timedelta(seconds=row.poll_interval_seconds)
    if key:
        db.add(DataSourceSyncReceipt(source_id=source_id,request_key=key))
    db.commit()
    return serialize(db,row)


async def poll_once():
    from ..database import SessionLocal
    with SessionLocal() as db:
        ids = db.execute(select(DataSource.id,DataSource.user_id).where(DataSource.provider=='binance_api', DataSource.paused.is_(False),
            or_(DataSource.next_sync_at.is_(None),DataSource.next_sync_at<=now()))).all()
    for source_id,user_id in ids:
        with SessionLocal() as db:
            try:
                # Recheck pause after enumeration.
                row=owned(db,user_id,source_id)
                if not row.paused:
                    await synchronize(db,user_id,source_id)
            except Exception:
                db.rollback()  # never log exception containing signed request or decrypted credentials


async def scheduler_loop():
    while True:
        try:
            await poll_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(15)


async def valuation_components(db, user_id, graph, base):
    """Only persisted observations. No live fetch from read paths; no mutation of manual assets."""
    rows=db.scalars(select(DataSource).where(DataSource.user_id==user_id)).all()
    components=[]
    for row in rows:
        data=serialize(db,row)
        snapshot=row.snapshot or {}
        # PM USD equity is authoritative, never value PM nominal positions again.
        values=[]
        for b in snapshot.get('balances',[]):
            if b.get('included_in_pm_equity'):
                continue
            from .exchange_rate.valuation import converted
            if b.get('value_usdt') is not None:
                values.append(converted(b['value_usdt'], await graph.resolve('USDT',base)))
            else:
                values.append(converted(b['net_equity'],await graph.resolve(b['asset'],base)))
        pm=snapshot.get('pm_equity')
        if pm:
            from .exchange_rate.valuation import converted
            values.append(converted(pm['amount'],await graph.resolve(pm['currency'],base)))
        from .investment_valuation import total, known
        complete=bool(snapshot) and all(m['status']=='ok' for m in snapshot.get('modules',[]))
        amount=total(values) if complete and row.status!='error' and not data['stale'] else None
        components.append(dict(id=row.id,kind='data_source_equity',name=row.name,account_id=row.account_id,
            coverage_policy=row.coverage_policy,currency=base,amount=amount,amount_base=amount,
            known_amount_base=known(values),as_of=snapshot.get('source_time'),stale=data['stale'],
            status=row.status,modules=data['modules'],balance_semantics='net_equity_not_notional_positions',
            available_balance=None))
    return components
