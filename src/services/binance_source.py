"""Binance HMAC REST adapter. No caller-controlled hosts, paths, methods or commands.

Funding's POST is a query, explicitly authorized; all other operations are GET.
Transport logs are suppressed because httpx INFO contains signed query strings.
"""
import asyncio
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode
import httpx

for _name in ('httpx', 'httpcore'):
    logging.getLogger(_name).setLevel(logging.WARNING)

ENDPOINTS = {
    'time': ('GET', 'https://api.binance.com', '/api/v3/time', False),
    'prices': ('GET', 'https://api.binance.com', '/api/v3/ticker/price', False),
    'spot': ('GET', 'https://api.binance.com', '/api/v3/account', True),
    'funding': ('POST', 'https://api.binance.com', '/sapi/v1/asset/get-funding-asset', True),
    'earn_flexible': ('GET', 'https://api.binance.com', '/sapi/v1/simple-earn/flexible/position', True),
    'portfolio_margin': ('GET', 'https://papi.binance.com', '/papi/v1/account', True),
    'pm_balances': ('GET', 'https://papi.binance.com', '/papi/v1/balance', True),
    'pm_um_positions': ('GET', 'https://papi.binance.com', '/papi/v1/um/positionRisk', True),
    'pm_cm_positions': ('GET', 'https://papi.binance.com', '/papi/v1/cm/positionRisk', True),
    'usd_m_futures': ('GET', 'https://fapi.binance.com', '/fapi/v3/account', True),
    'coin_m_futures': ('GET', 'https://dapi.binance.com', '/dapi/v1/account', True),
    'trades': ('GET', 'https://api.binance.com', '/api/v3/myTrades', True),
    'deposits': ('GET', 'https://api.binance.com', '/sapi/v1/capital/deposit/hisrec', True),
    'withdrawals': ('GET', 'https://api.binance.com', '/sapi/v1/capital/withdraw/history', True),
    'transfers': ('GET', 'https://api.binance.com', '/sapi/v1/asset/transfer', True),
    'earn_rewards': ('GET', 'https://api.binance.com', '/sapi/v1/simple-earn/flexible/history/rewardsRecord', True),
}
MODULES = ('spot','funding','earn_flexible','portfolio_margin','usd_m_futures','coin_m_futures')


class SourceError(Exception):
    """Only safe static codes may escape the adapter; never upstream body/url."""


class BinanceAdapter:
    def __init__(self, credentials, client=None):
        self.key, self.secret = credentials['api_key'], credentials['api_secret']
        self.client = client
        self.offset = 0
        self.last_request = 0

    async def request(self, endpoint, params=None):
        if endpoint not in ENDPOINTS:
            raise SourceError('endpoint_not_allowed')
        method, host, path, signed = ENDPOINTS[endpoint]
        for attempt in range(3):
            # Sequential, bounded request pacing, also honor exchange Retry-After.
            await asyncio.sleep(max(0, 1.0 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            payload = dict(params or {})
            if signed:
                payload.update(timestamp=int(time.time()*1000)+self.offset, recvWindow=5000)
            query = urlencode(payload)
            if signed:
                query += '&signature=' + hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            try:
                response = await self.client.request(method, host+path,
                    params=query if method == 'GET' else None,
                    content=query if method == 'POST' else None,
                    headers={'X-MBX-APIKEY':self.key, 'Content-Type':'application/x-www-form-urlencoded'},
                    timeout=httpx.Timeout(10, connect=5), follow_redirects=False)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt < 2:
                    await asyncio.sleep(.5 * 2**attempt)
                    continue
                raise SourceError('network_timeout') from None
            if response.status_code in (418,429) or response.status_code >= 500:
                if attempt < 2:
                    try:
                        delay = min(30, max(.5, float(response.headers.get('Retry-After', .5*2**attempt))))
                    except ValueError:
                        delay = 1
                    await asyncio.sleep(delay)
                    continue
                raise SourceError('rate_limited' if response.status_code in (418,429) else 'upstream_unavailable')
            if response.status_code != 200:
                raise SourceError('http_'+str(response.status_code))
            try:
                data = response.json()
            except ValueError:
                raise SourceError('invalid_response') from None
            if isinstance(data, dict) and isinstance(data.get('code'), int) and data['code'] < 0:
                raise SourceError('binance_'+str(data['code']))
            return data
        raise SourceError('request_failed')

    async def collect(self, symbols, cursors):
        if self.client is None:
            async with httpx.AsyncClient() as client:
                self.client = client
                return await self.collect(symbols, cursors)
        try:
            server = await self.request('time')
            self.offset = int(server['serverTime']) - int(time.time()*1000)
        except (SourceError, KeyError, TypeError, ValueError):
            raise SourceError('clock_sync_failed') from None
        observed_at = datetime.now(timezone.utc).isoformat()
        now = datetime.fromtimestamp(int(server['serverTime'])/1000, timezone.utc).isoformat()
        prices = {'USDT':Decimal(1)}  # USDT unit, never USD peg assumption
        try:
            for p in await self.request('prices'):
                if p['symbol'].endswith('USDT'):
                    prices[p['symbol'][:-4]] = Decimal(p['price'])
        except (SourceError, KeyError, TypeError, ValueError):
            pass
        balances, positions, modules = [], [], []
        def balance(module, asset, amount, available=None, pnl=None, wallet=None):
            amount = Decimal(str(amount))
            if not amount.is_finite():
                raise SourceError('invalid_decimal')
            price = prices.get(asset)
            balances.append(dict(module=module, asset=asset, balance=str(wallet) if wallet is not None else str(amount),
                net_equity=str(amount), available=str(available) if available is not None else None,
                unrealized_pnl=str(pnl) if pnl is not None else None,
                value_usdt=str(amount*price) if price is not None else ('0' if amount == 0 else None), source_time=now))
        pm_ok = False
        pm_equity = None
        for module in MODULES:
            try:
                if module in ('usd_m_futures','coin_m_futures') and pm_ok:
                    # PM already includes derivative equity; never add notional or wallet equity twice.
                    modules.append(dict(id=module,status='ok',error=None,source_time=now,coverage='included_in_portfolio_margin'))
                    continue
                if module == 'earn_flexible':
                    rows = []
                    for page in range(1,101):
                        batch = await self.request(module, {'current':page,'size':100})
                        rows.extend(batch['rows'])
                        if len(rows) >= int(batch['total']):
                            break
                    else:
                        raise SourceError('pagination_limit')
                    data = rows
                else:
                    data = await self.request(module)
                if module == 'spot':
                    for b in data['balances']:
                        balance(module,b['asset'],Decimal(b['free'])+Decimal(b['locked']),b['free'])
                elif module == 'funding':
                    for b in data:
                        balance(module,b['asset'],sum((Decimal(b[k]) for k in ('free','locked','freeze','withdrawing')),Decimal(0)),b['free'])
                elif module == 'earn_flexible':
                    for b in data:
                        balance(module,b['asset'],b['totalAmount'])
                elif module == 'portfolio_margin':
                    # accountEquity is USD per official PM account response; convert separately.
                    pm_equity = dict(currency='USD', amount=str(Decimal(data['accountEquity'])),source_time=now)
                    pm_data = await self.request('pm_balances')
                    for b in pm_data:
                        balances.append(dict(module=module,asset=b['asset'],balance=str(b['totalWalletBalance']),
                            net_equity=None,available=str(b['crossMarginFree']) if 'crossMarginFree' in b else None,
                            unrealized_pnl=str(b['umUnrealizedPNL']) if 'umUnrealizedPNL' in b else None,value_usdt=None,source_time=now,
                            included_in_pm_equity=True))
                    pm_ok = True
                    for endpoint in ('pm_um_positions','pm_cm_positions'):
                        try:
                            for p in await self.request(endpoint):
                                positions.append(dict(module=module,symbol=p['symbol'],quantity=str(p['positionAmt']),
                                    notional=str(p['notional']) if 'notional' in p else None,
                                    unrealized_pnl=str(p['unRealizedProfit']) if 'unRealizedProfit' in p else None,
                                    included_in_equity=True,source_time=now,product=endpoint))
                        except (SourceError,KeyError,ValueError,TypeError):
                            modules.append(dict(id=endpoint,status='unknown',error='positions_unavailable',source_time=None))
                else:
                    for b in data['assets']:
                        balance(module,b['asset'],b['marginBalance'],b.get('availableBalance'),b.get('unrealizedProfit'),b.get('walletBalance'))
                    for p in data['positions']:
                        positions.append(dict(module=module,symbol=p['symbol'],quantity=str(p['positionAmt']),
                            notional=str(p['notional']) if p.get('notional') is not None else None,
                            unrealized_pnl=str(p['unrealizedProfit']) if 'unrealizedProfit' in p else None,included_in_equity=True))
                modules.append(dict(id=module,status='ok',error=None,source_time=now))
            except (SourceError, KeyError, ValueError, TypeError, ArithmeticError) as exc:
                # Partial module results must not become authoritative zeros.
                balances[:] = [b for b in balances if b['module'] != module]
                positions[:] = [p for p in positions if p['module'] != module]
                if module == 'portfolio_margin':
                    pm_equity = None
                modules.append(dict(id=module,status='unknown',error=str(exc) if isinstance(exc,SourceError) else 'invalid_response',source_time=None))
        events, history, new_cursors = await self.history(symbols, cursors, now)
        vals = [Decimal(b['value_usdt']) for b in balances if b['value_usdt'] is not None]
        complete = all(m['status']=='ok' for m in modules) and all(b['value_usdt'] is not None or b.get('included_in_pm_equity') for b in balances)
        return dict(modules=modules,balances=balances,positions=positions,source_time=now,
            observed_at=observed_at,source_time_status='exchange_server_time_at_sync_start_not_price_tick',
            valuation_date=now[:10],valuation_currency='USDT',pm_equity=pm_equity,
            known_net_equity=str(sum(vals,Decimal(0))),
            net_equity=str(sum(vals,Decimal(0))) if complete and pm_equity is None else None,
            history_coverage=history), events, new_cursors

    async def history(self, symbols, cursors, now):
        events, coverage, updated = [], [], dict(cursors)
        end = int(time.time()*1000)
        # Fixed narrow first-sync window, subsequently persistent cursor + overlap + id dedup.
        specs = [(f'trades:{s}','trades',{'symbol':s},'id') for s in symbols]
        specs += [('deposits','deposits',{},'id'),('withdrawals','withdrawals',{},'id'),
            ('transfers:MAIN_UMFUTURE','transfers',{'type':'MAIN_UMFUTURE'},'tranId'),
            ('transfers:UMFUTURE_MAIN','transfers',{'type':'UMFUTURE_MAIN'},'tranId'),
            *[(f'earn_rewards:{reward}','earn_rewards',{'type':reward},None) for reward in ('BONUS','REALTIME','REWARDS')]]
        coverage.append(dict(id='other_transfer_types',status='unknown',error='only_MAIN_UMFUTURE_and_UMFUTURE_MAIN_covered'))
        if not symbols:
            coverage.append(dict(id='trades',status='unknown',error='symbols_required'))
        for kind, endpoint, extra, id_field in specs:
            start = int(updated.get(kind, end-24*3600*1000))
            stop = min(end, start+24*3600*1000-1)
            try:
                collected = []
                limit = 1000 if endpoint in ('trades','deposits','withdrawals') else 100
                for page in range(1,21):
                    params = dict(extra, startTime=start,endTime=stop)
                    if endpoint in ('trades','deposits','withdrawals'):
                        params['limit'] = limit
                        if endpoint != 'trades':
                            params['offset'] = (page-1)*limit
                        elif page > 1:
                            # fromId cannot combine with start/end on Spot myTrades.
                            params.pop('startTime'); params.pop('endTime')
                            params['fromId'] = int(collected[-1]['id'])+1
                    else:
                        params.update(current=page,size=limit)
                    data = await self.request(endpoint,params)
                    rows = data if isinstance(data,list) else data.get('rows',[])
                    if endpoint == 'trades':
                        rows = [r for r in rows if int(r.get('time',0)) <= stop]
                    collected.extend(rows)
                    if len(rows) < limit:
                        break
                else:
                    raise SourceError('history_pagination_limit')
                for e in collected:
                    external_id = str(e[id_field]) if id_field else hashlib.sha256(__import__('json').dumps(e,sort_keys=True).encode()).hexdigest()
                    events.append(dict(kind=kind,external_id=external_id,payload=e))
                updated[kind] = stop  # overlap boundary deliberately, ids provide dedup
                coverage.append(dict(id=kind,status='ok',error=None,start_time=start,end_time=stop,complete_history=False))
            except (SourceError, KeyError, TypeError, ValueError) as exc:
                coverage.append(dict(id=kind,status='unknown',error=str(exc) if isinstance(exc,SourceError) else 'invalid_response'))
        return events, coverage, updated
