import asyncio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.services.binance_source import BinanceAdapter, SourceError
from src.error_handling import register_exception_handlers
from src.routers.data_sources import router
from src.deps import get_current_user
from src.routers.write._shared import _WRITE_SCOPE_DEP
from src.models import User


def test_timeout_retries_three_times_and_safe_error(monkeypatch):
    calls=[]; sleeps=[]
    async def sleep(delay): sleeps.append(delay)
    monkeypatch.setattr('src.services.binance_source.asyncio.sleep',sleep)
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('secret-in-transport-diagnostic',request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=BinanceAdapter({'api_key':'sensitive-key','api_secret':'sensitive-secret'},client)
            with pytest.raises(SourceError) as caught:
                await adapter.request('spot')
            assert str(caught.value)=='network_timeout'
    asyncio.run(run())
    assert len(calls)==3 and .5 in sleeps and 1.0 in sleeps


def test_rate_limit_retry_after_then_success(monkeypatch):
    calls=[]; sleeps=[]
    async def sleep(delay): sleeps.append(delay)
    monkeypatch.setattr('src.services.binance_source.asyncio.sleep',sleep)
    def handler(request):
        calls.append(request)
        return httpx.Response(429,headers={'Retry-After':'2'},json={'msg':'sensitive-upstream'}) if len(calls)<3 else httpx.Response(200,json={'balances':[]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result=await BinanceAdapter({'api_key':'key','api_secret':'secret'},client).request('spot')
            assert result=={'balances':[]}
    asyncio.run(run())
    assert len(calls)==3 and sleeps.count(2)==2


def test_history_pagination_cap_does_not_advance_cursor():
    adapter=BinanceAdapter({'api_key':'k','api_secret':'s'})
    async def request(endpoint,params=None):
        if endpoint=='trades':
            return [{'id':i,'time':1} for i in range(1000)]
        raise SourceError('http_403')
    adapter.request=request
    events,coverage,cursors=asyncio.run(adapter.history(['BTCUSDT'],{'trades:BTCUSDT':123},'now'))
    assert not events and cursors['trades:BTCUSDT']==123
    assert next(h for h in coverage if h['id']=='trades:BTCUSDT')['error']=='history_pagination_limit'
    assert all(c['status']=='unknown' for c in coverage)


def test_validation_response_never_echoes_credentials():
    app=FastAPI(); app.include_router(router,prefix='/api/v1'); register_exception_handlers(app)
    app.dependency_overrides[get_current_user]=lambda:User(id='u')
    app.dependency_overrides[_WRITE_SCOPE_DEP]=lambda:None
    from src.database import get_db
    app.dependency_overrides[get_db]=lambda:None
    client=TestClient(app)
    secret='DO-NOT-ECHO-THIS-SECRET'
    result=client.post('/api/v1/data-sources',json={'name':'','credentials':{'api_key':secret,'api_secret':secret},'poll_interval_seconds':0})
    assert result.status_code==422 and secret not in result.text
    assert 'input' not in result.text
