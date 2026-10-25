"""Single valuation contract shared by authenticated REST and registered MCP tools."""
from datetime import datetime, timezone
from sqlalchemy import select
from ..models import InvestmentProduct, UserProfile
from .investment_accounts import investment_account_cash_balances
from .exchange_rate.valuation import ConversionGraph, converted, iso


def total(values):
    values = list(values)
    return round(sum(values), 2) if all(v is not None for v in values) else None


def known(values):
    return round(sum(v for v in values if v is not None), 2)


async def investment_assets(db, user_id, refresh=True):
    from .investment_price import fetch_price
    base = (db.scalar(select(UserProfile.primary_currency).where(UserProfile.user_id == user_id)) or 'CNY').upper()
    rows = db.scalars(select(InvestmentProduct).where(InvestmentProduct.user_id == user_id).order_by(InvestmentProduct.name)).all()
    graph = ConversionGraph(db, user_id)
    accounts = investment_account_cash_balances(db, user_id=user_id)
    from .data_sources import valuation_components
    source_components = await valuation_components(db, user_id, graph, base)
    replaced_accounts = {c['account_id'] for c in source_components if c['coverage_policy'] == 'replace_bound_account'}
    accounts = {key:value for key,value in accounts.items() if key not in replaced_accounts}
    rows = [row for row in rows if row.account_id not in replaced_accounts]
    items = []
    for row in rows:
        mode = 'money_fund' if row.is_money_fund else row.valuation_mode
        price, day_change = row.current_price, row.day_change
        daily_income = row.daily_income
        if refresh and mode != 'amount_snapshot' and (row.is_money_fund or row.price_source != 'manual'):
            try:
                quote = await fetch_price(row.symbol, 'fund' if row.is_money_fund else row.market)
                if quote.get('price') is not None:
                    row.current_price = price = quote['price']
                    row.price_source = quote.get('source')
                    row.price_updated_at = datetime.now(timezone.utc)
                    row.last_market_close = quote.get('previous_close')
                    row.day_change = day_change = quote.get('day_change')
                if row.is_money_fund and quote.get('daily_income_per_10000') is not None:
                    daily_income = row.quantity / 10000 * quote['daily_income_per_10000']
                db.commit()
            except Exception:
                pass
        quantity = float(row.quantity)
        cost = (0.0 if quantity == 0 else row.net_subscription_principal) if mode == 'money_fund' else (0.0 if quantity == 0 else quantity * row.cost_basis if row.cost_basis is not None else None)
        if mode == 'amount_snapshot':
            value = row.snapshot_amount
            cost = None  # amount snapshots do not imply units or cost
            daily = None
        else:
            price = 1.0 if mode == 'money_fund' else price
            value = 0.0 if quantity == 0 else quantity * price if price is not None else None
            daily = 0.0 if quantity == 0 else daily_income if mode == 'money_fund' else quantity * day_change if day_change is not None else None
        pnl = value - cost if value is not None and cost is not None else None
        fx = await graph.resolve(row.currency, base)
        item = dict(id=row.id, name=row.name, symbol=row.symbol, market=row.market,
            currency=row.currency, base_currency=base, account_id=row.account_id, account_name=row.account_name,
            quantity=quantity, cost_basis=row.cost_basis, cost_basis_total=cost,
            current_price=price, price=price, last_market_close=row.last_market_close, day_change=day_change,
            price_mode='manual' if row.price_source == 'manual' else 'auto',
            price_status='snapshot' if mode == 'amount_snapshot' else 'manual' if row.price_source == 'manual' else 'live' if price is not None else 'missing',
            price_source=row.price_source, price_updated_at=iso(row.price_updated_at),
            valuation_mode=mode, snapshot_amount=row.snapshot_amount, snapshot_at=iso(row.snapshot_at),
            valuation_source=row.valuation_source, as_of=iso(row.snapshot_at if mode == 'amount_snapshot' else row.price_updated_at),
            market_value=value, daily_pnl=daily, holding_pnl=pnl, fx=fx,
            market_value_base=converted(value, fx), daily_pnl_base=converted(daily, fx),
            holding_pnl_base=converted(pnl, fx), cost_basis_total_base=converted(cost, fx),
            is_money_fund=bool(row.is_money_fund), daily_income=daily_income)
        items.append(item)
    account_items = []
    for account_id, data in accounts.items():
        children = [item for item in items if item['account_id'] == account_id]
        fx = await graph.resolve(data['currency'], base)
        cash = converted(data['cash_balance'], fx)
        value = total(item['market_value_base'] for item in children)
        # Existing account totals remain in ACCOUNT currency, never mix holding currencies.
        native_values = [converted(item['market_value'], await graph.resolve(item['currency'], data['currency'])) for item in children]
        native_pnls = [converted(item['daily_pnl'], await graph.resolve(item['currency'], data['currency'])) for item in children]
        account_items.append(dict(**data, fx=fx, base_currency=base, cash_balance_base=cash,
            holdings_market_value=total(native_values), holdings_market_value_base=value,
            total_assets=total([data['cash_balance'], total(native_values)]),
            total_assets_base=total([cash, value]), net_equity_base=total([cash, value]),
            available_balance=None, available_balance_status='not_reported',
            daily_pnl=total(native_pnls), daily_pnl_base=total(item['daily_pnl_base'] for item in children), items=children))
    values = [item['market_value_base'] for item in items]
    cash_values = [item['cash_balance_base'] for item in account_items]
    daily_values = [item['daily_pnl_base'] for item in items]
    unbound = [item['id'] for item in items if item['account_id'] not in accounts]
    missing = [item['id'] for item in items if item['market_value_base'] is None]
    source_values = [c['amount_base'] for c in source_components]
    result = dict(base_currency=base, scope='investment_only', all_assets_total=None,
        data_source_components=source_components, replaced_account_ids=sorted(replaced_accounts),
        total_market_value=total(values), total_daily_pnl=total(daily_values),
        total_cash_balance=total(cash_values), total_assets=total(values + cash_values + source_values),
        net_equity=total(values + cash_values + source_values), available_balance=None,
        known_market_value=known(values), known_cash_balance=known(cash_values), known_total_assets=known(values + cash_values) + sum(c['known_amount_base'] for c in source_components),
        coverage=dict(holdings_total=len(items), holdings_valued=len(items)-len(missing), missing_holding_ids=missing,
                      cash_accounts_total=len(account_items), cash_accounts_valued=sum(v is not None for v in cash_values), unbound_holding_ids=unbound),
        completeness='complete' if not missing and not unbound and all(v is not None for v in cash_values + source_values) else 'partial',
        as_of=datetime.now(timezone.utc).isoformat(), as_of_status='mixed_observation_times',
        valuation_times_complete=all(item['as_of'] is not None for item in items),
        cash_times_complete=all(data.get('cash_as_of') is not None for data in accounts.values()),
        fx_stale=any(item['fx']['stale'] for item in items) or any(item['fx']['stale'] for item in account_items),
        investment_accounts=account_items, items=items)

    from .asset_summary import all_assets
    result['all_assets_summary'] = await all_assets(db, user_id, result)
    result['all_assets_total'] = result['all_assets_summary']['total_assets']
    return result
