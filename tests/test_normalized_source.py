import asyncio
from datetime import timedelta
from src.services import data_sources as service
from src.services.investment_valuation import investment_assets
from test_data_sources import env


def make(client,**kw):
    return client.post('/api/v1/data-sources',json=dict(name='External CLI',provider='normalized_json',**kw))


def payload(**kw):
    return dict(schema_version=1,source_time=service.now().isoformat(),
        modules=[{'id':'spot','status':'ok'}],balances=[dict(module='spot',asset='USDT',balance='10.000000000001',
            net_equity='10.000000000001',available='8',value_usdt='10.000000000001')],
        events=[dict(kind='trade',external_id='external-1',payload={'qty':'0.01'})],**kw)


def test_schema_provider_crud_ingest_precision_and_dedup(env):
    factory,client,_=env
    providers=client.get('/api/v1/data-sources/providers').json()['items']
    assert next(p for p in providers if p['id']=='normalized_json')['available']
    schema=client.get('/api/v1/data-sources/schema').json()
    assert schema['properties']['schema_version']['const']==1
    made=make(client); assert made.status_code==201,made.text
    sid=made.json()['id']; path=f'/api/v1/data-sources/{sid}/ingest'
    assert not made.json()['credentials_configured']
    body=payload()
    result=client.post(path,json=body,headers={'Idempotency-Key':'export-1'})
    assert result.status_code==200,result.text
    data=result.json()
    assert data['status']=='partial' and data['net_equity'] is None
    assert data['balances'][0]['balance']=='10.000000000001'
    assert data['event_count']==1 and len(data['modules'])==6
    assert client.post(path,json=body).json()['event_count']==1
    assert client.post(path,json=body,headers={'Idempotency-Key':'export-1'}).json()['event_count']==1
    changed=payload(); changed['balances'][0]['balance']='999'
    assert client.post(path,json=changed,headers={'Idempotency-Key':'export-1'}).status_code==409
    assert client.post(f'/api/v1/data-sources/{sid}/sync').status_code==422
    client.patch(f'/api/v1/data-sources/{sid}',json={'paused':True})
    assert client.post(path,json=body).status_code==409
    client.patch(f'/api/v1/data-sources/{sid}',json={'paused':False})
    old=payload(); old['source_time']=(service.now()-timedelta(days=2)).isoformat()
    assert client.post(path,json=old).status_code==409
    client.delete(f'/api/v1/data-sources/{sid}')
    assert client.post(path,json=body).status_code==404


def test_invalid_import_no_commands_credentials_or_fake_precision(env):
    _,client,_=env
    assert make(client,credentials={'api_key':'x','api_secret':'y'}).status_code==422
    sid=make(client).json()['id']; path=f'/api/v1/data-sources/{sid}/ingest'
    for change in ('numeric','nan','command','naive','unknown','pm_double','future'):
        body=payload()
        if change=='numeric': body['balances'][0]['balance']=10.1
        if change=='nan': body['balances'][0]['balance']='NaN'
        if change=='command': body['command']='binance withdraw'
        if change=='naive': body['source_time']='2026-01-01T00:00:00'
        if change=='unknown': body['modules'][0]['status']='unknown'
        if change=='pm_double':
            body['modules'].append({'id':'portfolio_margin','status':'ok'})
            body['pm_equity']={'amount':'100'}
            body['balances'].append(dict(module='portfolio_margin',asset='USDT',balance='100'))
        if change=='future': body['source_time']=(service.now()+timedelta(days=1)).isoformat()
        result=client.post(path,json=body)
        assert result.status_code==422,(change,result.text)


def test_import_staleness_follows_observation_not_upload(env):
    factory,client,_=env
    sid=make(client,account_id='a',coverage_policy='replace_bound_account').json()['id']
    body=payload(); body['source_time']=(service.now()-timedelta(days=2)).isoformat()
    data=client.post(f'/api/v1/data-sources/{sid}/ingest',json=body).json()
    assert data['stale']
    with factory() as db:
        result=asyncio.run(investment_assets(db,'u',False))
        assert result['total_assets'] is None and result['all_assets_total'] is None
        assert result['replaced_account_ids']==['a']


def test_import_tenant_scope(env):
    _,client,app=env
    sid=make(client).json()['id']
    from src.deps import get_current_user
    from src.models import User
    app.dependency_overrides[get_current_user]=lambda:User(id='other')
    assert client.post(f'/api/v1/data-sources/{sid}/ingest',json=payload()).status_code==404
