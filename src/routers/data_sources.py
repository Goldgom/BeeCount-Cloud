"""Authenticated Cloud data-source API. Secrets are write-only, no arbitrary shell."""
import re
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from uuid import uuid4
from ..services.normalized_source import ImportSnapshot, ingest
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from ..database import get_db
from ..deps import get_current_user
from ..models import User, UserAccountProjection
from ..models_data_sources import DataSource, DataSourceEvent, DataSourceSyncReceipt
from .read._shared import _READ_SCOPE_DEP
from .write._shared import _WRITE_SCOPE_DEP
from ..services import data_sources as service
from ..services.binance_source import MODULES

router=APIRouter(prefix='/data-sources',tags=['data-sources'])


class Credentials(BaseModel):
    api_key: SecretStr
    api_secret: SecretStr

    @field_validator('api_key','api_secret')
    @classmethod
    def valid_secret(cls, value):
        if not 1 <= len(value.get_secret_value()) <= 512:
            raise ValueError('Credential length must be 1..512')
        return value


class CreateSource(BaseModel):
    name: str=Field(min_length=1,max_length=120)
    provider: Literal['binance_api','normalized_json']='binance_api'
    credentials: Credentials | None=None

    @model_validator(mode='after')
    def provider_credentials(self):
        if self.provider=='binance_api' and self.credentials is None:
            raise ValueError('Binance API requires credentials')
        if self.provider=='normalized_json' and self.credentials is not None:
            raise ValueError('JSON imports must not contain exchange credentials')
        return self
    account_id: str | None=None
    coverage_policy: Literal['replace_bound_account','separate']='separate'
    poll_interval_seconds: int=Field(default=300,ge=60,le=86400)
    paused: bool=False
    symbols: list[str]=Field(default_factory=list,max_length=20)

    @field_validator('symbols')
    @classmethod
    def valid_symbols(cls, value):
        if any(not re.fullmatch(r'[A-Z0-9]{4,30}',s) for s in value):
            raise ValueError('Symbols must be Binance uppercase trading pairs')
        return list(dict.fromkeys(value))


class PatchSource(BaseModel):
    name: str | None=Field(default=None,min_length=1,max_length=120)
    credentials: Credentials | None=None
    account_id: str | None=None
    coverage_policy: Literal['replace_bound_account','separate'] | None=None
    poll_interval_seconds: int | None=Field(default=None,ge=60,le=86400)
    paused: bool | None=None
    symbols: list[str] | None=Field(default=None,max_length=20)

    @field_validator('symbols')
    @classmethod
    def valid_symbols(cls,value):
        return CreateSource.valid_symbols(value) if value is not None else value


def store_credentials(value):
    return service.encrypt({k:getattr(value,k).get_secret_value() for k in ('api_key','api_secret')})


@router.get('/providers')
def providers(user: User=Depends(get_current_user), _scope=Depends(_READ_SCOPE_DEP)):
    return {'items':[dict(id='binance_api',name='Binance signed REST (read-only)',available=True,modules=list(MODULES)),
        dict(id='binance_cli',name='Binance CLI',available=False,reason='Use normalized_json for externally normalized CLI exports; no server command execution'),
        dict(id='normalized_json',name='Standard JSON / external CLI export',available=True,modules=list(MODULES))]}


@router.get('/schema')
def import_schema(user: User=Depends(get_current_user),_scope=Depends(_READ_SCOPE_DEP)):
    return ImportSnapshot.model_json_schema()


@router.post('/{source_id}/ingest')
def import_snapshot(source_id: str,body: ImportSnapshot,
        idempotency_key: str | None=Header(default=None,alias='Idempotency-Key'),
        user: User=Depends(get_current_user),db: Session=Depends(get_db),_scope=Depends(_WRITE_SCOPE_DEP)):
    return ingest(db,user.id,source_id,body,idempotency_key)


@router.get('/accounts')
def accounts(user: User=Depends(get_current_user),db: Session=Depends(get_db),_scope=Depends(_READ_SCOPE_DEP)):
    return {'items':[dict(id=a.sync_id,name=a.name,currency=a.currency) for a in db.scalars(
        select(UserAccountProjection).where(UserAccountProjection.user_id==user.id)).all()]}


@router.get('')
def list_sources(user: User=Depends(get_current_user),db: Session=Depends(get_db),_scope=Depends(_READ_SCOPE_DEP)):
    return {'items':[service.serialize(db,r) for r in db.scalars(select(DataSource).where(DataSource.user_id==user.id)).all()]}


@router.post('',status_code=201)
def create(body: CreateSource,user: User=Depends(get_current_user),db: Session=Depends(get_db),_scope=Depends(_WRITE_SCOPE_DEP)):
    data=body.model_dump(exclude={'credentials'})
    service.validate_binding(db,user.id,data)
    row=DataSource(user_id=user.id,credentials_encrypted=store_credentials(body.credentials) if body.credentials else '',**data)
    db.add(row); db.commit(); db.refresh(row)
    return service.serialize(db,row)


@router.get('/{source_id}')
def detail(source_id: str,user: User=Depends(get_current_user),db: Session=Depends(get_db),_scope=Depends(_READ_SCOPE_DEP)):
    return service.serialize(db,service.owned(db,user.id,source_id))


@router.patch('/{source_id}')
def patch(source_id: str,body: PatchSource,user: User=Depends(get_current_user),db: Session=Depends(get_db),_scope=Depends(_WRITE_SCOPE_DEP)):
    row=service.owned(db,user.id,source_id)
    if row.lock_until and service.utc(row.lock_until)>service.now():
        raise HTTPException(409,'Wait for active sync to finish before editing')
    data=body.model_dump(exclude_unset=True,exclude={'credentials'})
    if any(v is None for k,v in data.items() if k!='account_id'):
        raise HTTPException(422,'Only account_id may be null')
    service.validate_binding(db,user.id,dict(account_id=data.get('account_id',row.account_id),
        coverage_policy=data.get('coverage_policy',row.coverage_policy)),source_id)
    if body.credentials and row.provider!='binance_api':
        raise HTTPException(422,'Imported sources must not contain exchange credentials')
    invalidate=bool(body.credentials) or any(key in data and data[key]!=getattr(row,key) for key in ('account_id','coverage_policy'))
    for key,value in data.items():
        setattr(row,key,value)
    if body.credentials:
        row.credentials_encrypted=store_credentials(body.credentials)
    if invalidate:
        row.snapshot={}; row.cursors={}; row.last_success_at=None; row.status='never_synced'
        db.execute(delete(DataSourceSyncReceipt).where(DataSourceSyncReceipt.source_id==source_id))
    row.lock_token=str(uuid4())
    row.lock_until=None
    row.next_sync_at=service.now() if row.provider=='binance_api' else None
    db.commit()
    return service.serialize(db,row)


@router.delete('/{source_id}')
def remove(source_id: str,user: User=Depends(get_current_user),db: Session=Depends(get_db),_scope=Depends(_WRITE_SCOPE_DEP)):
    row=service.owned(db,user.id,source_id)
    # Explicit child deletes work even on SQLite installations without foreign_keys pragma.
    for model in (DataSourceEvent,DataSourceSyncReceipt):
        db.execute(delete(model).where(model.source_id==source_id))
    db.delete(row); db.commit()
    return {'deleted':True}


@router.post('/{source_id}/sync')
async def sync(source_id: str,idempotency_key: str | None=Header(default=None,alias='Idempotency-Key'),
        user: User=Depends(get_current_user),db: Session=Depends(get_db),_scope=Depends(_WRITE_SCOPE_DEP)):
    if idempotency_key is not None and not 1<=len(idempotency_key)<=128:
        raise HTTPException(422,'Idempotency-Key length must be 1..128')
    return await service.synchronize(db,user.id,source_id,idempotency_key)


@router.get('/{source_id}/events')
def events(source_id: str,offset: int=0,limit: int=100,user: User=Depends(get_current_user),
        db: Session=Depends(get_db),_scope=Depends(_READ_SCOPE_DEP)):
    service.owned(db,user.id,source_id)
    if offset<0 or not 1<=limit<=500:
        raise HTTPException(422,'Invalid pagination')
    rows=db.scalars(select(DataSourceEvent).where(DataSourceEvent.source_id==source_id)
        .order_by(DataSourceEvent.observed_at,DataSourceEvent.id).offset(offset).limit(limit)).all()
    return {'items':[dict(id=r.id,kind=r.kind,external_id=r.external_id,payload=r.payload,
        observed_at=service.iso(r.observed_at)) for r in rows], 'offset':offset,'limit':limit}
