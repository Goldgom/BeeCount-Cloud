import asyncio
import hashlib
import hmac
from datetime import timedelta
from urllib.parse import parse_qs
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.models import Base, User, UserAccountProjection, InvestmentProduct, UserExchangeRateProjection
from src.models_data_sources import DataSource, DataSourceEvent
from src.services import data_sources as service
from src.services.binance_source import BinanceAdapter, SourceError
from src.services.investment_valuation import investment_assets
from src.routers.data_sources import router
from src.database import get_db
from src.deps import get_current_user
from src.routers.read._shared import _READ_SCOPE_DEP
from src.routers.write._shared import _WRITE_SCOPE_DEP


@pytest.fixture
def env(monkeypatch):
    from src.config import get_settings
    monkeypatch.setattr(get_settings(),'exchange_rate_proxy_enabled',False)
    async def no_sleep(*args): pass
    monkeypatch.setattr('src.services.binance_source.asyncio.sleep', no_sleep)
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    with factory() as db:
        u=User(id='u',email='u@source.test',password_hash='x')
        db.add_all([u,User(id='other',email='other@source.test',password_hash='x')])
        db.add(UserAccountProjection(user_id='u',sync_id='a',name='Binance',currency='USDT',initial_balance=999,account_type='investment'))
        db.commit()
    app=FastAPI()
    app.include_router(router,prefix='/api/v1')
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db]=database
    app.dependency_overrides[get_current_user]=lambda:u
    app.dependency_overrides[_READ_SCOPE_DEP]=lambda:None
    app.dependency_overrides[_WRITE_SCOPE_DEP]=lambda:None
    return factory,TestClient(app),app


def create(client,**kw):
    return client.post('/api/v1/data-sources',json=dict(name='Binance',credentials={'api_key':'fixture-key','api_secret':'fixture-secret'},**kw))


def transport(seen, pm=False, spot_fail=False):
    def handler(req):
        seen.append(req)
        path=req.url.path
        if path not in ('/api/v3/time','/api/v3/ticker/price'):
            query=req.content.decode() if req.method=='POST' else req.url.query.decode()
            signed,signature=query.rsplit('&signature=',1)
            assert signature==hmac.new(b'fixture-secret',signed.encode(),hashlib.sha256).hexdigest()
            assert req.headers['X-MBX-APIKEY']=='fixture-key'
            params=parse_qs(signed)
            assert params['recvWindow']==['5000'] and 'timestamp' in params
        if path=='/api/v3/time':
            import time
            return httpx.Response(200,json={'serverTime':int(time.time()*1000)})
        if path=='/api/v3/ticker/price':
            return httpx.Response(200,json=[{'symbol':'BTCUSDT','price':'60000'}])
        if path=='/api/v3/account':
            return httpx.Response(403,json={}) if spot_fail else httpx.Response(200,json={'balances':[{'asset':'BTC','free':'0.00000001','locked':'0'},{'asset':'USDT','free':'10','locked':'1'}]})
        if path=='/sapi/v1/asset/get-funding-asset':
            assert req.method=='POST'  # only explicitly allowlisted query POST
            return httpx.Response(200,json=[{'asset':'USDT','free':'2','locked':'1','freeze':'0','withdrawing':'0'}])
        if path=='/sapi/v1/simple-earn/flexible/position':
            return httpx.Response(200,json={'rows':[{'asset':'USDT','totalAmount':'5'}],'total':1})
        if path=='/papi/v1/account':
            return httpx.Response(200,json={'accountEquity':'100'}) if pm else httpx.Response(403,json={})
        if path in ('/papi/v1/um/positionRisk','/papi/v1/cm/positionRisk'):
            return httpx.Response(200,json=[{'symbol':'BTCUSDT','positionAmt':'2','notional':'120000','unRealizedProfit':'20'}])
        if path=='/papi/v1/balance':
            return httpx.Response(200,json=[{'asset':'USDT','totalWalletBalance':'80','crossMarginFree':'3','umUnrealizedPNL':'20'}])
        if path in ('/fapi/v3/account','/dapi/v1/account'):
            return httpx.Response(200,json={'assets':[{'asset':'USDT','marginBalance':'4','availableBalance':'2','unrealizedProfit':'1'}],
                'positions':[{'symbol':'BTCUSDT','positionAmt':'2','notional':'120000','unrealizedProfit':'1'}]})
        if path=='/api/v3/myTrades':
            return httpx.Response(200,json=[{'id':7,'symbol':'BTCUSDT','time':1,'qty':'0.01','price':'60000'}])
        if path=='/sapi/v1/capital/deposit/hisrec':
            return httpx.Response(200,json=[{'id':'d1','amount':'2','coin':'USDT'}])
        if path=='/sapi/v1/capital/withdraw/history':
            return httpx.Response(403,json={})
        if path=='/sapi/v1/asset/transfer':
            return httpx.Response(200,json={'rows':[{'tranId':23,'amount':'3'}],'total':1})
        if path=='/sapi/v1/simple-earn/flexible/history/rewardsRecord':
            return httpx.Response(200,json={'rows':[{'asset':'USDT','rewards':'0.01','time':1}],'total':1})
        raise AssertionError(path)
    return httpx.MockTransport(handler)


def test_crud_secret_tenant_binding(env):
    factory,client,app=env
    response=create(client,account_id='a',coverage_policy='replace_bound_account')
    assert response.status_code==201,response.text
    data=response.json(); sid=data['id']
    assert data['stale'] and data['status']=='never_synced'
    assert 'fixture-key' not in response.text and 'fixture-secret' not in response.text
    with factory() as db:
        row=db.get(DataSource,sid)
        assert 'fixture-secret' not in row.credentials_encrypted
    assert create(client,account_id='a',coverage_policy='replace_bound_account').status_code==409
    assert create(client,account_id='missing',coverage_policy='replace_bound_account').status_code==422
    assert create(client,account_id='a').status_code==422
    assert client.patch(f'/api/v1/data-sources/{sid}',json={'paused':True}).json()['paused']
    app.dependency_overrides[get_current_user]=lambda:User(id='other')
    for method,path in [('get',''),('patch',''),('delete',''),('post','/sync'),('get','/events')]:
        kwargs={'json':{'paused':False}} if method=='patch' else {}
        assert getattr(client,method)(f'/api/v1/data-sources/{sid}'+path,**kwargs).status_code==404
    assert client.get('/api/v1/data-sources').json()=={'items':[]}


def test_signed_http_partial_snapshot_history_dedup_and_receipt(env):
    factory,client,_=env
    sid=create(client,symbols=['BTCUSDT']).json()['id']
    seen=[]
    async def run():
        async with httpx.AsyncClient(transport=transport(seen)) as http:
            with factory() as db:
                result=await service.synchronize(db,'u',sid,'same',client=http)
                assert result['status']=='partial'
                assert result['net_equity'] is None
                assert result['known_net_equity']=='27.00060000'
                assert next(m for m in result['modules'] if m['id']=='portfolio_margin')['status']=='unknown'
                assert next(h for h in result['history_coverage'] if h['id']=='withdrawals')['status']=='unknown'
                assert result['balances'][0]['balance']=='1E-8'
                count=result['event_count']; requests=len(seen)
                await service.synchronize(db,'u',sid,'same',client=http)
                assert len(seen)==requests
                again=await service.synchronize(db,'u',sid,'next',client=http)
                assert again['event_count']==count
                assert db.get(DataSource,sid).cursors['trades:BTCUSDT']
    asyncio.run(run())
    assert any(req.method=='POST' for req in seen)
    assert all(req.method=='GET' or req.url.path=='/sapi/v1/asset/get-funding-asset' for req in seen)


def test_pm_authoritative_equity_no_notional_or_derivative_double_count(env):
    factory,client,_=env
    sid=create(client,account_id='a',coverage_policy='replace_bound_account').json()['id']
    seen=[]
    async def run():
        async with httpx.AsyncClient(transport=transport(seen,pm=True)) as http:
            with factory() as db:
                db.add(UserExchangeRateProjection(user_id='u',sync_id='fx',base_currency='CNY',quote_currency='USDT',rate=1))
                db.add(UserExchangeRateProjection(user_id='u',sync_id='fx2',base_currency='USD',quote_currency='USDT',rate=1))
                db.add(InvestmentProduct(user_id='u',name='manual duplicate',symbol='X',account_id='a',currency='USDT',quantity=99,current_price=1,price_source='manual'))
                db.commit()
                data=await service.synchronize(db,'u',sid,client=http)
                assert data['pm_equity']['amount']=='100'
                assert data['net_equity'] is None  # USD != USDT
                assert not any(req.url.host in ('fapi.binance.com','dapi.binance.com') for req in seen)
                result=await investment_assets(db,'u',False)
                assert result['items']==[]
                assert result['total_assets']==119.00  # existing summary rounds to base cents; raw balance remains exact
                assert result['all_assets_total']==119.00
                assert db.scalar(select(UserAccountProjection.initial_balance))==999
                source=db.get(DataSource,sid)
                source.last_success_at=service.now()-timedelta(days=1); db.commit()
                stale=await investment_assets(db,'u',False)
                assert stale['total_assets'] is None
    asyncio.run(run())


def test_lease_pause_and_delete(env,monkeypatch):
    factory,client,_=env
    sid=create(client,paused=True).json()['id']
    with factory() as db:
        row=db.get(DataSource,sid)
        row.lock_until=service.now()+timedelta(minutes=5); db.commit()
    assert client.post(f'/api/v1/data-sources/{sid}/sync').status_code==409
    assert client.patch(f'/api/v1/data-sources/{sid}',json={'name':'x'}).status_code==409
    from src import database
    monkeypatch.setattr(database,'SessionLocal',factory)
    called=[]
    async def sync(*args,**kwargs): called.append(args)
    monkeypatch.setattr(service,'synchronize',sync)
    asyncio.run(service.poll_once())
    assert not called
    assert client.delete(f'/api/v1/data-sources/{sid}').json()=={'deleted':True}
    assert client.get(f'/api/v1/data-sources/{sid}').status_code==404


def test_no_arbitrary_endpoints_or_cli(env):
    _,client,_=env
    assert create(client,provider='binance_cli').status_code==422
    assert client.get('/api/v1/data-sources/providers').json()['items'][1]['available'] is False
    async def run():
        adapter=BinanceAdapter({'api_key':'x','api_secret':'y'})
        with pytest.raises(SourceError,match='endpoint_not_allowed'):
            await adapter.request('https://example.com/trade')
    asyncio.run(run())
