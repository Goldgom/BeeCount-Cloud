import type { InvestmentAssetsResponse } from '@beecount/api-client'
import { Card, CardContent, CardHeader, CardTitle, useT } from '@beecount/ui'
import { Amount } from '@beecount/web-features'
import { investmentObservation, investmentPnl } from '../../lib/investmentPresentation'

export function HomeInvestmentHoldings({ data }: { data: InvestmentAssetsResponse | null }) {
  const t = useT()
  if (!data || (data.investment_accounts.length === 0 && data.items.length === 0)) return null
  const coverage = data.coverage
  return (
    <Card className="overflow-hidden">
      <CardHeader className="gap-4 border-b border-border/50 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <CardTitle>{t('accounts.investment.holdings')}</CardTitle>
          <p className="text-xs text-muted-foreground">{t('accounts.investment.scope')}</p>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded-full bg-muted px-2.5 py-1">{data.base_currency}</span>
            <span className="rounded-full bg-muted px-2.5 py-1">{data.completeness === 'partial' ? t('accounts.investment.partial') : data.completeness === 'complete' ? t('accounts.investment.complete') : t('accounts.investment.coverageUnknown')}</span>
            {coverage ? <span className="py-1 text-muted-foreground">{t('accounts.investment.coverage', { valued: coverage.holdings_valued, total: coverage.holdings_total })}</span> : null}
          </div>
        </div>
        <div className="sm:text-right">
          <p className="text-xs text-muted-foreground">{t('accounts.investment.investmentAssets')}</p>
          <Amount value={data.total_assets} currency={data.base_currency} showCurrency size="2xl" bold compact={false} />
          <div className="mt-2 text-xs text-muted-foreground">{t('accounts.investment.dailyPnl')} <Pnl value={data.total_daily_pnl} currency={data.base_currency} /></div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 pt-5 sm:pt-6">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl bg-muted/50 p-4"><p className="mb-1 text-xs text-muted-foreground">{t('accounts.investment.cash')}</p><Amount value={data.total_cash_balance} currency={data.base_currency} showCurrency compact={false} /></div>
          <div className="rounded-xl bg-muted/50 p-4"><p className="mb-1 text-xs text-muted-foreground">{t('accounts.investment.totalValue')}</p><Amount value={data.total_market_value} currency={data.base_currency} showCurrency compact={false} /></div>
        </div>
        {data.completeness === 'partial' ? <p role="status" className="rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-xs leading-relaxed text-muted-foreground">{t('accounts.investment.partialHint')}</p> : null}
        <div className="overflow-x-auto rounded-xl border border-border/50" tabIndex={0} role="region" aria-label={t('accounts.investment.holdings')}>
          <table className="bc-investment-table">
            <caption className="sr-only">{t('accounts.investment.scope')}</caption>
            <thead><tr>
              {['product', 'quantity', 'costPrice', 'marketPrice', 'marketValue', 'holdingPnl', 'dailyPnl'].map((key) => <th scope="col" key={key}>{t(`accounts.investment.${key}`)}</th>)}
            </tr></thead>
            <tbody>{data.items.map((item) => {
              const observation = investmentObservation(item)
              const snapshot = item.valuation_mode === 'amount_snapshot'
              return <tr key={item.id}>
                <td><div className="font-medium">{item.name}</div><div className="mt-1 text-xs text-muted-foreground">{[item.symbol, item.market, item.account_name, item.currency].filter(Boolean).join(' · ')}</div><div className="mt-1 text-xs text-muted-foreground">{snapshot ? t('accounts.investment.snapshot') : item.price_status === 'manual' ? t('accounts.investment.manualPrice') : item.price_status === 'fallback' || item.price_status === 'missing' ? t('accounts.investment.unavailable') : t('accounts.investment.autoPrice')}{item.valuation_source ? ` · ${item.valuation_source}` : ''}</div><div className="mt-1 text-xs text-muted-foreground">{observation || t('accounts.investment.timeUnknown')}</div>{(item.fx?.stale || item.fx?.path?.some((leg) => leg.stale)) ? <div className="mt-1 text-xs text-amber-700 dark:text-amber-400">{t('accounts.investment.staleFx')}</div> : null}</td>
                <td>{snapshot ? '—' : item.quantity.toLocaleString()}</td>
                <td>{snapshot ? '—' : <Amount value={item.cost_basis} currency={item.currency} showCurrency compact={false} />}</td>
                <td>{snapshot ? '—' : <Amount value={item.current_price} currency={item.currency} showCurrency compact={false} />}</td>
                <td><Amount value={item.market_value} currency={item.currency} showCurrency compact={false} /></td>
                <td><Pnl value={item.holding_pnl} currency={item.currency} /></td>
                <td><Pnl value={item.daily_pnl} currency={item.currency} /></td>
              </tr>
            })}</tbody>
          </table>
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">{t('accounts.investment.observationHint')}{data.as_of ? ` · ${t('accounts.investment.generatedAt')}: ${data.as_of}` : ''}</p>
      </CardContent>
    </Card>
  )
}

function Pnl({ value, currency }: { value: number | null | undefined; currency: string }) {
  const presentation = investmentPnl(value)
  return <Amount value={presentation.value} currency={currency} showCurrency compact={false} sign="always" tone={presentation.tone} />
}
