import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { LocaleProvider } from '@beecount/ui'
import type { InvestmentAssetsResponse } from '@beecount/api-client'
import { investmentObservation, investmentPnl } from './investmentPresentation'
import { HomeInvestmentHoldings } from '../components/dashboard/HomeInvestmentHoldings'
import { dictionaries } from '../i18n'

const data: InvestmentAssetsResponse = {
  base_currency: 'CNY', total_assets: null, total_cash_balance: 100,
  total_market_value: null, total_daily_pnl: null,
  completeness: 'partial', scope: 'investment_only', as_of: '2026-10-25T10:28:00Z',
  coverage: { holdings_total: 1, holdings_valued: 0, missing_holding_ids: ['missing'], cash_accounts_total: 1, cash_accounts_valued: 1, unbound_holding_ids: [] },
  investment_accounts: [],
  items: [{ id: 'missing', name: 'Unknown fund', symbol: 'TEST', currency: 'USD', market: null, account_id: null, account_name: null, quantity: 20, cost_basis: 10, current_price: null, last_market_close: null, day_change: null, price_mode: 'auto', market_value: null, daily_pnl: null, holding_pnl: null }],
}

describe('investment presentation', () => {
  it('unknown and non-finite PnL is not zero or positive', () => {
    for (const value of [null, undefined, NaN, Infinity]) expect(investmentPnl(value)).toEqual({ value: null, tone: 'muted' })
    expect(investmentPnl(0)).toEqual({ value: 0, tone: 'default' })
    expect(investmentPnl(-2).tone).toBe('negative')
  })
  it('keeps observation dates distinct from generated time', () => {
    expect(investmentObservation({ as_of: null, snapshot_at: '2026-10-23', price_updated_at: '2026-10-25' })).toBe('2026-10-23')
    expect(investmentObservation({})).toBeNull()
  })
  it('renders missing estimates without crashes, zero returns, or claiming all assets', () => {
    const html = renderToStaticMarkup(<LocaleProvider dictionaries={dictionaries}><HomeInvestmentHoldings data={data} /></LocaleProvider>)
    expect(html).toContain('Unknown fund')
    expect(html).toContain('USD')
    expect(html).toContain('—')
    expect(html).not.toContain('+0.00')
    expect(html).toContain('Partial valuation')
    expect(html).toContain('not all assets')
    expect(html).toContain('Observation time unavailable')
    expect(html).toContain('Valued 0 / 1 holdings')
  })
  it('snapshot valuation never presents amount as units or a market quote', () => {
    const snapshot = { ...data, items: [{ ...data.items[0], valuation_mode: 'amount_snapshot' as const, snapshot_at: '2026-10-20', valuation_source: 'Statement', market_value: 1200 }] }
    const html = renderToStaticMarkup(<LocaleProvider dictionaries={dictionaries}><HomeInvestmentHoldings data={snapshot} /></LocaleProvider>)
    expect(html).toContain('Amount snapshot')
    expect(html).toContain('Statement')
    expect(html).toContain('2026-10-20')
    expect(html).not.toContain('>20</td>')
  })
})
