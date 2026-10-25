from datetime import datetime, timezone, timedelta
import asyncio
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.database import Base, get_db
from src.models import User, UserAccountProjection, ReadTxProjection
from src.models_finance import FinanceEvent
from src.services import finance
from src.routers import finance as router

@pytest.fixture
def setup():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        user = User(id='u', email='finance@test.com', password_hash='x')
        db.add(user)
        for aid, currency, balance in [('a','CNY',100),('b','USD',10)]:
            db.add(UserAccountProjection(user_id='u',sync_id=aid,name=aid,account_type='investment',currency=currency,initial_balance=balance))
        db.add(User(id='other', email='other@test.com', password_hash='x'))
        db.commit()
    return factory, user

def op(db, kind, key, **data):
    result = finance.execute(db,user_id='u',kind=kind,key=key,data=data)
    db.commit()
    return result

def balance(db, aid='a'):
    return finance.account_balances(db,user_id='u')[aid]['cash_balance']

def test_reconcile_replay_conflict_reverse_and_real_cash(setup):
    factory, _ = setup
    with factory() as db:
        at = (datetime.now(timezone.utc)-timedelta(seconds=2)).isoformat()
        data = dict(account_id='a',effective_at=at,target_balance='120.25',expected_balance='100',source='statement',reason='missing old records')
        first = op(db,'reconciliation','r1',**data)
        assert first['payload']['difference'] == '20.25' and balance(db)==120.25
        assert op(db,'reconciliation','r1',**data)['id']==first['id']
        with pytest.raises(HTTPException) as exc:
            op(db,'reconciliation','r1',**{**data,'target_balance':'130'})
        assert exc.value.status_code==409
        db.rollback()
        with pytest.raises(HTTPException):
            op(db,'reconciliation','r2',**{**data,'effective_at':datetime.now(timezone.utc).isoformat()})
        db.rollback()
        assert db.scalar(select(UserAccountProjection).where(UserAccountProjection.sync_id=='a')).initial_balance==100
        assert db.scalars(select(ReadTxProjection)).all()==[]
        from src.services.investment_accounts import investment_account_cash_balances
        assert investment_account_cash_balances(db,user_id='u')['a']['cash_balance']==120.25
        reversal=op(db,'reversal','undo',event_id=first['id'],reason='wrong statement')
        assert reversal['effects']=={'a':'-20.25'} and balance(db)==100
        with pytest.raises(HTTPException):
            op(db,'reversal','undo2',event_id=first['id'],reason='again')
        db.rollback()
        assert finance.events(db,'other')==[]

def test_cross_currency_atomic_dedup_and_fee(setup):
    factory,_=setup
    with factory() as db:
        data=dict(from_account_id='a',to_account_id='b',from_amount='70',to_amount='10',
                  from_currency='CNY',to_currency='USD',fee_amount='1',fee_account_id='a',fee_currency='CNY',
                  external_id='bank-123',source='bank')
        result=op(db,'transfer','t',**data)
        assert result['effects']=={'a':'-71','b':'10'}
        assert balance(db)==29 and balance(db,'b')==20
        op(db,'transfer','t',**data)
        assert balance(db)==29
        with pytest.raises(HTTPException) as exc:
            op(db,'transfer','t2',**data)
        assert exc.value.status_code==409
        db.rollback()
        with pytest.raises(HTTPException):
            op(db,'transfer','bad',**{**data,'external_id':'new','to_currency':'CNY'})
        db.rollback()
        assert len(finance.events(db,'u'))==1 and balance(db)==29

def test_installment_partial_repayments(setup):
    factory,_=setup
    with factory() as db:
        parent=op(db,'receivable','r',amount='50',currency='CNY',counterparty='friend',reason='advance')
        assert balance(db)==100
        installment=op(db,'receivable_installment','i',receivable_id=parent['id'],amount='30',due_at='2026-11-01T00:00:00+08:00')
        op(db,'repayment','p',receivable_id=parent['id'],installment_id=installment['id'],amount='10',account_id='a')
        op(db,'repayment','p2',receivable_id=parent['id'],installment_id=installment['id'],amount='15',account_id='a')
        summary=finance.receivables(db,'u')[0]
        assert summary['remaining']=='25' and summary['installments'][0]['remaining']=='5'
        assert balance(db)==125
        with pytest.raises(HTTPException):
            op(db,'repayment','over',receivable_id=parent['id'],installment_id=installment['id'],amount='6',account_id='a')
        db.rollback()
        assert balance(db)==125

def test_immutable_daily_snapshot_and_honest_report(setup):
    factory,_=setup
    with factory() as db:
        snapshot=op(db,'snapshot','s',trigger='manual')
        assert snapshot['payload']['accounts']['a']['cash_balance']==100
        op(db,'reconciliation','r',account_id='a',target_balance='110',expected_balance='100',
           effective_at=datetime.now(timezone.utc).isoformat(),source='broker',reason='observed')
        assert finance.events(db,'u')[0].payload['accounts']['a']['cash_balance']==100
        with pytest.raises(HTTPException) as exc:
            op(db,'snapshot','s2')
        assert exc.value.status_code==409
        db.rollback()
        report=finance.period_report(db,'u','2026-01-01T00:00:00Z','2027-01-01T00:00:00Z')
        assert report['asset_change'] is None and report['investment_return'] is None
        op(db,'investment_event','e',account_id='a',currency='CNY',amount='3',classification='dividend_reinvested',source='fund statement',reason='confirmed')
        assert balance(db)==110

def test_rest_and_mcp_registration(setup,monkeypatch):
    factory,user=setup
    app=FastAPI();app.include_router(router.router,prefix='/api/v1')
    def db_dep():
        with factory() as db: yield db
    app.dependency_overrides[get_db]=db_dep
    app.dependency_overrides[router.get_current_user]=lambda:user
    app.dependency_overrides[router.read_scope]=lambda:set()
    app.dependency_overrides[router.write_scope]=lambda:set()
    client=TestClient(app)
    assert client.post('/api/v1/finance/events',json={'kind':'receivable','data':{}}).status_code==422
    response=client.post('/api/v1/finance/events',headers={'Idempotency-Key':'rest'},json={
        'kind':'transfer','data':{'from_account_id':'a','to_account_id':'b','from_amount':'7','to_amount':'1',
                                'from_currency':'CNY','to_currency':'USD','source':'bank','external_id':'rest'}})
    assert response.status_code==200,response.text
    assert client.get('/api/v1/finance/balances').json()['a']['cash_balance']==93
    from mcp.server.fastmcp import FastMCP
    from src.mcp.tools import finance_tools
    monkeypatch.setattr(finance_tools,'SessionLocal',factory)
    mcp=FastMCP('test')
    async def logged(ctx,**kw): return await kw['body'](user)
    finance_tools.register(mcp,logged)
    result=asyncio.run(mcp.call_tool('finance_read',{'view':'balances'}))
    assert result
    assert {'finance_read','finance_operation'} <= {t.name for t in asyncio.run(mcp.list_tools())}
    notifications=[]
    class Manager:
        async def broadcast_to_user(self, user_id, payload):
            notifications.append((user_id,payload))
    monkeypatch.setattr(finance_tools,'_ws_manager',Manager())
    written=asyncio.run(mcp.call_tool('finance_operation',{'kind':'receivable','idempotency_key':'mcp',
        'data':{'amount':'8','currency':'CNY','counterparty':'friend','reason':'loan'}}))
    assert written
    assert notifications[0][0]=='u' and notifications[0][1]['entity_type']=='finance_event'
    with factory() as db:
        assert finance.receivables(db,'u')[0]['remaining']=='8'


def test_daily_scheduler_capture_and_lifecycle(setup, monkeypatch):
    from src.services.finance_scheduler import capture_daily, FinanceSnapshotScheduler
    from src.config import get_settings
    factory,_=setup
    assert capture_daily(factory)['failed']==0
    assert capture_daily(factory)['failed']==0
    with factory() as db:
        rows=db.scalars(select(FinanceEvent).where(FinanceEvent.kind=='snapshot')).all()
        assert len(rows)==2  # one immutable observation per user, not per invocation
        assert {e.payload['day'] for e in rows}=={datetime.now(timezone.utc).date().isoformat()}
        assert {e.payload['trigger'] for e in rows}=={'daily_scheduler_utc'}
    scheduler=FinanceSnapshotScheduler()
    monkeypatch.setattr(get_settings(),'finance_snapshot_scheduler_enabled',False)
    scheduler.start()
    assert scheduler.scheduler is None
    monkeypatch.setattr(get_settings(),'finance_snapshot_scheduler_enabled',True)
    monkeypatch.setattr('src.services.finance_scheduler.SessionLocal',factory)
    scheduler.start()
    assert str(scheduler.scheduler.timezone)=='UTC'
    jobs={j.id:j for j in scheduler.scheduler.get_jobs()}
    assert 'finance-daily-utc' in jobs
    scheduler.shutdown()
    assert scheduler.scheduler is None


def test_multiledger_original_currency_and_workspace_read(setup):
    from src.models import Ledger, LedgerMember
    from src.routers.read.workspace import list_workspace_accounts
    factory,user=setup
    with factory() as db:
        for lid in ('l1','l2'):
            db.add(Ledger(id=lid,user_id='u',external_id=lid,name=lid,currency='CNY'))
            db.add(LedgerMember(ledger_id=lid,user_id='u',role='owner'))
            db.add(ReadTxProjection(ledger_id=lid,sync_id='same-tx-id',user_id='u',tx_type='income',
                amount=2,native_amount=14,currency_code='USD',account_sync_id='b',account_name='b',
                happened_at=datetime.now(timezone.utc)-timedelta(seconds=5)))
        # Old data without stable ID resolves only an unambiguous account name.
        db.add(ReadTxProjection(ledger_id='l1',sync_id='old',user_id='u',tx_type='income',amount=3,
            account_name='a',happened_at=datetime.now(timezone.utc)-timedelta(seconds=5)))
        db.commit()
        assert balance(db,'b')==14  # 10 USD + 2 USD + 2 USD, never +14 CNY
        assert balance(db)==103
        op(db,'reconciliation','read',account_id='b',target_balance='20',expected_balance='14',
            effective_at=datetime.now(timezone.utc).isoformat(),source='broker',reason='observed')
        rows=list_workspace_accounts(ledger_id=None,user_id=None,q=None,limit=500,offset=0,
                                     _scopes=set(),current_user=user,db=db)
        result={row.id:row for row in rows}
        assert result['b'].balance==20 and result['b'].income_total==4
        assert result['b'].initial_balance==10
        with pytest.raises(HTTPException):
            finance.execute(db,user_id='other',kind='reconciliation',key='steal',data={
                'account_id':'b','target_balance':'0','expected_balance':'20','source':'x','reason':'x',
                'effective_at':datetime.now(timezone.utc).isoformat()})
        db.rollback()
