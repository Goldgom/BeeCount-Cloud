"""All-assets composition: account CASH + standalone holdings + outstanding receivables.

Never add investment-account total_assets/net_equity again: it already includes
its linked holdings. This scope is separate from the investment-only summary.
"""
from .finance import account_balances, receivables
from .exchange_rate.valuation import ConversionGraph, converted
from .investment_valuation import total, known


async def all_assets(db, user_id, investment):
    graph = ConversionGraph(db, user_id)
    base = investment['base_currency']
    accounts = account_balances(db, user_id=user_id)
    components = []
    for account_id, account in accounts.items():
        if account_id in investment.get('replaced_account_ids', []):
            continue
        fx = await graph.resolve(account['currency'], base)
        components.append(dict(id=account_id, kind='account_cash', name=account['account_name'],
            currency=account['currency'], amount=account['cash_balance'],
            amount_base=converted(account.get('balance_decimal', account['cash_balance']), fx), fx=fx,
            as_of=account.get('cash_as_of'), balance_semantics='cash_not_broker_net_equity',
            available_balance=None))
    for item in investment['items']:
        components.append(dict(id=item['id'], kind='investment_holding', name=item['name'],
            currency=item['currency'], amount=item['market_value'], amount_base=item['market_value_base'],
            fx=item['fx'], as_of=item['as_of']))
    for item in receivables(db, user_id):
        currency = item['payload']['currency']
        fx = await graph.resolve(currency, base)
        components.append(dict(id=item['id'], kind='receivable', name=item['payload'].get('name'),
            currency=currency, amount=float(item['remaining']), amount_base=converted(item['remaining'], fx),
            fx=fx, as_of=item['effective_at']))
    components.extend(investment.get('data_source_components', []))
    values = [item['amount_base'] for item in components]
    missing = [item['id'] for item in components if item['amount_base'] is None]
    return dict(scope='all_assets', base_currency=base, total_assets=total(values), net_equity=total(values),
        known_total_assets=known(values) + sum(c.get('known_amount_base', 0) for c in components if c['kind']=='data_source_equity' and c['amount_base'] is None), available_balance=None,
        composition='account_cash_plus_holdings_plus_outstanding_receivables_plus_external_equity',
        coverage=dict(components_total=len(components), components_valued=len(components)-len(missing), missing_component_ids=missing),
        completeness='partial' if missing else 'complete',
        as_of=investment['as_of'], as_of_status='mixed_observation_times',
        valuation_times_complete=all(item['as_of'] is not None for item in components),
        components=components)
