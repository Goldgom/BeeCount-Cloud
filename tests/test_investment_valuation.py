import asyncio
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.database import Base, get_db
from src.models import User, UserAccountProjection, InvestmentProduct, UserExchangeRateProjection
from src.services.investment_valuation import investment_assets
from src.services.exchange_rate.valuation import ConversionGraph
from src.routers.investment_products import InvestmentProductCreate, InvestmentProductPatch, create_investment_product, update_investment_product


@pytest.fixture
def setup(monkeypatch):
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), 'exchange_rate_proxy_enabled', False)
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        user = User(id='u', email='p0@test.com', password_hash='x')
        db.add(user)
        db.add(UserAccountProjection(user_id='u', sync_id='a', name='Broker', account_type='investment', currency='CNY', initial_balance=50))
        db.commit()
    return factory, user


def holding(db, **kwargs):
    row = InvestmentProduct(user_id='u', name='USDT position', symbol='USDT', account_id='a', currency='USDT', quantity=10, current_price=2, price_source='manual', **kwargs)
    db.add(row); db.commit()
    return row


def rates(db):
    for id, base, quote, rate in [('u-usd','USD','USDT','0.98'), ('usd-cny','CNY','USD','7.1')]:
        db.add(UserExchangeRateProjection(user_id='u', sync_id=id, base_currency=base, quote_currency=quote, rate=rate))
    db.commit()


def test_missing_rate_never_one_to_one(setup):
    factory, _ = setup
    with factory() as db:
        holding(db)
        result = asyncio.run(investment_assets(db, 'u', False))
        item = result['items'][0]
        assert item['market_value'] == 20
        assert item['market_value_base'] is None
        assert item['daily_pnl'] is None and item['holding_pnl'] is None
        assert item['cost_basis_total'] is None
        assert result['total_assets'] is None and result['known_total_assets'] == 50
        assert result['completeness'] == 'partial'
        assert item['fx']['status'] == 'missing_rate'


def test_multihop_usdt_cost_and_account_currency(setup):
    factory, _ = setup
    with factory() as db:
        row = holding(db, cost_basis=1.5, day_change=0.1)
        rates(db)
        result = asyncio.run(investment_assets(db, 'u', False))
        item = result['items'][0]
        assert item['cost_basis_total'] == 15
        assert item['market_value_base'] == 139.16
        assert item['daily_pnl_base'] == pytest.approx(6.958)
        assert len(item['fx']['path']) == 2
        assert item['fx']['path'][0]['source'] == 'user_override:u-usd'
        assert result['total_assets'] == 189.16
        assert result['investment_accounts'][0]['holdings_market_value'] == 139.16
        assert result['scope'] == 'investment_only' and result['all_assets_total'] == 189.16
        row.quantity = 0; db.commit()
        item = asyncio.run(investment_assets(db, 'u', False))['items'][0]
        assert item['cost_basis_total'] == 0 and item['holding_pnl'] == 0


def test_snapshot_moneyfund_and_unknown_price(setup):
    factory, user = setup
    with factory() as db:
        snapshot = create_investment_product(InvestmentProductCreate(name='Snapshot', symbol='S', account_id='a', quantity=999, valuation_mode='amount_snapshot', snapshot_amount=123, snapshot_at=datetime.now(timezone.utc), valuation_source='broker statement'), current_user=user, db=db)
        fund = create_investment_product(InvestmentProductCreate(name='Fund', symbol='F', account_id='a', quantity=100, is_money_fund=True), current_user=user, db=db)
        noquote = create_investment_product(InvestmentProductCreate(name='No quote', symbol='N', account_id='a', quantity=2, cost_basis=10), current_user=user, db=db)
        rows = {item['id']:item for item in asyncio.run(investment_assets(db,'u',False))['items']}
        assert rows[snapshot.id]['market_value'] == 123 and rows[snapshot.id]['cost_basis_total'] is None
        assert rows[fund.id]['market_value'] == 100 and rows[fund.id]['holding_pnl'] is None and rows[fund.id]['daily_pnl'] is None
        assert rows[noquote.id]['market_value'] is None
        update_investment_product(noquote.id, InvestmentProductPatch(clear_cost_basis=True), current_user=user, db=db)
        assert db.get(InvestmentProduct, noquote.id).cost_basis is None


def test_rest_and_mcp_real_entrypoints(setup, monkeypatch):
    from src.main import app
    from src.deps import get_current_user
    from src.routers.read._shared import _READ_SCOPE_DEP
    from src.mcp.tools import read_tools, write_tools
    from src.mcp.server import mcp
    factory, user = setup
    monkeypatch.setattr(read_tools, 'SessionLocal', factory)
    monkeypatch.setattr(write_tools, 'SessionLocal', factory)
    created = asyncio.run(write_tools.create_investment_product(user, name='MCP', symbol='U', quantity=2, account_id='a', currency='USDT', current_price=5))
    with factory() as db:
        rates(db)
        assert db.get(InvestmentProduct, created['id']).cost_basis is None
    def dep():
        with factory() as db:
            yield db
    app.dependency_overrides.update({get_db:dep, get_current_user:lambda:user, _READ_SCOPE_DEP:lambda:set()})
    try:
        rest = TestClient(app).get('/api/v1/read/investment-assets?refresh=false')
        assert rest.status_code == 200, rest.text
        api = rest.json(); tool = asyncio.run(read_tools.get_investment_assets(user, refresh=False))
        api.pop('as_of'); tool.pop('as_of')
        for response in (api, tool):
            for account in response['investment_accounts']:
                account.pop('cash_as_of', None)
            for component in response['all_assets_summary']['components']:
                if component['kind'] == 'account_cash':
                    component.pop('as_of', None)
            response['all_assets_summary'].pop('as_of')
        assert api == tool
        tools = asyncio.run(mcp.list_tools())
        schemas = {t.name:t.inputSchema for t in tools}
        assert 'valuation_mode' in schemas['create_investment_product']['properties']
        assert 'clear_cost_basis' in schemas['update_investment_product']['properties']
    finally:
        app.dependency_overrides.clear()


def test_reported_usdt_account_balances_use_configured_rate(setup):
    factory, _ = setup
    with factory() as db:
        # Test data only: real conversion must come from the user's rate projection.
        db.add(UserExchangeRateProjection(user_id='u', sync_id='configured-usdt', base_currency='CNY', quote_currency='USDT', rate='6.6702'))
        for id, amount in [('binance-1',1298.99), ('binance-2',556.27)]:
            db.add(UserAccountProjection(user_id='u', sync_id=id, name=id, account_type='investment', currency='USDT', initial_balance=amount))
        db.add(UserAccountProjection(user_id='u', sync_id='bank', name='Bank', account_type='bank', currency='CNY', initial_balance=100))
        db.commit()
        result = asyncio.run(investment_assets(db,'u',False))
        usdt_accounts = [a for a in result['investment_accounts'] if a['currency'] == 'USDT']
        assert sum(a['cash_balance_base'] for a in usdt_accounts) == pytest.approx(12374.955252)
        assert result['total_assets'] == 12424.96  # plus existing broker cash 50
        assert result['all_assets_total'] == 12524.96  # plus bank 100, no double-count
        assert result['all_assets_summary']['coverage']['components_total'] == 4


def test_receivable_repayment_is_not_double_counted(setup):
    from src.services.finance import execute
    factory, _ = setup
    with factory() as db:
        debt = execute(db, user_id='u', kind='receivable', key='r', data={'counterparty':'Client','currency':'CNY','reason':'advance','amount':'200'})
        db.commit()
        before = asyncio.run(investment_assets(db,'u',False))
        assert before['all_assets_total'] == 250
        execute(db,user_id='u',kind='repayment',key='p',data={'receivable_id':debt['id'],'account_id':'a','amount':'70'})
        db.commit()
        after = asyncio.run(investment_assets(db,'u',False))
        assert after['total_cash_balance'] == 120
        assert after['all_assets_total'] == 250
        component = next(c for c in after['all_assets_summary']['components'] if c['kind']=='receivable')
        assert component['amount'] == 130


def test_invalid_amount_snapshot_and_nonfinite_inputs(setup):
    from fastapi import HTTPException
    from pydantic import ValidationError
    factory, user = setup
    with factory() as db:
        with pytest.raises(HTTPException):
            create_investment_product(InvestmentProductCreate(name='Bad',symbol='B',account_id='a',valuation_mode='amount_snapshot',snapshot_amount=10),current_user=user,db=db)
        with pytest.raises(ValidationError):
            InvestmentProductCreate(name='Bad',symbol='B',quantity=float('inf'))
        with pytest.raises(ValidationError):
            InvestmentProductPatch(cost_basis=-1)


def test_cache_inverse_stale_and_user_override_priority(setup):
    from src.models import ExchangeRateCache
    from datetime import timedelta
    factory, _ = setup
    with factory() as db:
        db.add(ExchangeRateCache(base_currency='CNY', payload_json={'USD':'0.125','BAD':'NaN'}, source='test_provider', rate_date='2026-10-20', fetched_at=datetime.now(timezone.utc)-timedelta(days=5)))
        db.add(UserExchangeRateProjection(user_id='other',sync_id='other',base_currency='CNY',quote_currency='USDT',rate='100'))
        db.commit()
        graph = ConversionGraph(db,'u')
        fx = asyncio.run(graph.resolve('USD','CNY'))
        assert float(fx['rate']) == 8 and fx['stale']
        assert fx['path'][0]['source'] == 'test_provider'
        assert fx['path'][0]['rate_date'] == '2026-10-20'
        assert asyncio.run(graph.resolve('USDT','CNY'))['status'] == 'missing_rate'
        assert asyncio.run(graph.resolve('BAD','CNY'))['status'] == 'missing_rate'
        db.add(UserExchangeRateProjection(user_id='u',sync_id='mine',base_currency='CNY',quote_currency='USD',rate='7'))
        db.commit()
        assert float(ConversionGraph(db,'u').find('USD','CNY')['rate']) == 7
