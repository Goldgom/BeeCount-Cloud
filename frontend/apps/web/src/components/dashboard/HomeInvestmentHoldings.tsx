import type { InvestmentAssetsResponse } from '@beecount/api-client'
import { Card, CardContent, CardHeader, CardTitle, useT } from '@beecount/ui'
import { Amount } from '@beecount/web-features'

export function HomeInvestmentHoldings({ data }: { data: InvestmentAssetsResponse | null }) {
  const t = useT()
  if (!data || data.investment_accounts.length === 0) return null
  return (
    <Card className="overflow-hidden border-pink-500/20 bg-gradient-to-br from-pink-500/[0.08] via-card to-card">
      <CardHeader className="flex flex-row items-end justify-between gap-3 pb-3">
        <div>
          <CardTitle className="text-base">{t('accounts.investment.holdings')}</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">{t('accounts.investment.subtitle')}</p>
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Total assets</div>
          <Amount value={data.total_assets} currency={data.base_currency} showCurrency bold />
          <div className="text-[10px] text-muted-foreground">Cash {data.total_cash_balance.toFixed(2)} · Holdings {data.total_market_value.toFixed(2)}</div>
          <div className={data.total_daily_pnl >= 0 ? 'text-xs text-emerald-600' : 'text-xs text-rose-600'}>
            {data.total_daily_pnl >= 0 ? '+' : ''}{data.total_daily_pnl.toFixed(2)} {t('accounts.investment.dailyPnl')}
          </div>
        </div>
      </CardHeader>
      <CardContent className="overflow-x-auto pt-0">
        <table className="w-full min-w-[760px] text-xs">
          <thead><tr className="border-b text-left text-[10px] uppercase tracking-wide text-muted-foreground">
            <th className="px-2 py-2">{t('accounts.investment.product')}</th><th className="px-2 py-2">{t('accounts.investment.quantity')}</th><th className="px-2 py-2">{t('accounts.investment.costPrice')}</th><th className="px-2 py-2">{t('accounts.investment.marketPrice')}</th><th className="px-2 py-2">{t('accounts.investment.marketValue')}</th><th className="px-2 py-2">{t('accounts.investment.holdingPnl')}</th><th className="px-2 py-2">{t('accounts.investment.dailyPnl')}</th>
          </tr></thead>
          <tbody>{data.items.map((item) => <tr key={item.id} className="border-b last:border-0">
            <td className="px-2 py-2"><div className="font-medium">{item.name}</div><div className="text-[10px] text-muted-foreground">{item.symbol}{item.market ? ` · ${item.market}` : ''}{item.account_name ? ` · ${item.account_name}` : ''}</div></td>
            <td className="px-2 py-2">{item.quantity}</td><td className="px-2 py-2">{item.cost_basis.toFixed(2)}</td><td className="px-2 py-2"><div>{item.current_price?.toFixed(2) ?? '—'}</div>{item.day_change !== null ? <div className={item.day_change >= 0 ? 'text-[10px] text-emerald-600' : 'text-[10px] text-rose-600'}>{item.day_change >= 0 ? '+' : ''}{item.day_change.toFixed(2)} / day</div> : null}</td><td className="px-2 py-2"><Amount value={item.market_value} currency={item.currency} showCurrency /></td>
            <td className={item.holding_pnl >= 0 ? 'px-2 py-2 text-emerald-600' : 'px-2 py-2 text-rose-600'}>{item.holding_pnl >= 0 ? '+' : ''}{item.holding_pnl.toFixed(2)}</td><td className={item.daily_pnl >= 0 ? 'px-2 py-2 text-emerald-600' : 'px-2 py-2 text-rose-600'}>{item.daily_pnl >= 0 ? '+' : ''}{item.daily_pnl.toFixed(2)}</td>
          </tr>)}</tbody>
        </table>
      </CardContent>
    </Card>
  )
}
