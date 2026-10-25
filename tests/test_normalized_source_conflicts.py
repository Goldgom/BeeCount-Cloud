import asyncio
from test_data_sources import env
from test_normalized_source import make,payload
from src.services.investment_valuation import investment_assets


def test_same_observation_conflict_and_duplicate_batch_events(env):
    _,client,_=env
    sid=make(client).json()['id']; path=f'/api/v1/data-sources/{sid}/ingest'
    body=payload(); body['events']*=2
    first=client.post(path,json=body)
    assert first.status_code==200 and first.json()['event_count']==1
    assert client.post(path,json=body).status_code==200
    body['balances'][0]['balance']='11'
    assert client.post(path,json=body).status_code==409


def test_conflicting_event_ids_in_batch_and_existing_store(env):
    _,client,_=env
    sid=make(client).json()['id']; path=f'/api/v1/data-sources/{sid}/ingest'
    body=payload()
    assert client.post(path,json=body).status_code==200
    changed=payload(); changed['events'][0]['payload']={'qty':'2'}
    assert client.post(path,json=changed).status_code==409
    another=payload(); another['events'].append(dict(kind='trade',external_id='external-1',payload={'qty':'3'}))
    assert client.post(path,json=another).status_code==409
    assert client.get(f'/api/v1/data-sources/{sid}').json()['event_count']==1


def test_unknown_equity_null_and_pm_coverage_requires_equity(env):
    factory,client,_=env
    sid=make(client).json()['id']; path=f'/api/v1/data-sources/{sid}/ingest'
    body=payload(); body['balances'][0]['net_equity']=None; body['balances'][0]['value_usdt']=None
    assert client.post(path,json=body).status_code==200
    with factory() as db:
        result=asyncio.run(investment_assets(db,'u',False))
        assert result['total_assets'] is None
    pm=payload(); pm['modules'].append({'id':'portfolio_margin','status':'ok'})
    assert client.post(path,json=pm).status_code==422
