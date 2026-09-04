import type { InvestmentAssetsResponse } from '@beecount/api-client'
import { Card, CardContent, CardHeader, CardTitle, useT } from '@beecount/ui'
import { Amount } from '@beecount/web-features'

export function HomeInvestmentHoldings({ data }: { data: InvestmentAssetsResponse | null }) {
  const t = useT()
  if (!data || data.items.length === 0) return null
  return (
    <Card className="overflow-hidden border-pink-500/20 bg-gradient-to-br from-pink-500/[0.08] via-card to-card">
      <CardHeader className="flex flex-row items-end justify-between gap-3 pb-3">
        <div>
          <CardTitle className="text-base">{t('accounts.investment.holdings')}</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">{t('accounts.investment.subtitle')}</p>
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{t('accounts.investment.totalValue')}</div>
          <Amount value={data.total_market_value} currency={data.base_currency} showCurrency bold />
          <div className={data.total_daily_pnl >= 0 ? 'text-xs text-emerald-600' : 'text-xs text-rose-600'}>
            {data.total_daily_pnl >= 0 ? '+' : ''}{data.total_daily_pnl.toFixed(2)} {t('accounts.investment.dailyPnl')}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 pt-0">
        {data.items.slice(0, 6).map((item) => (
          <div key={item.id} className="flex items-center gap-3 rounded-xl border border-border/50 bg-background/50 px-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{item.name}</div>
              <div className="truncate text-xs text-muted-foreground">{item.symbol}{item.market ? ` · ${item.market}` : ''} · {item.quantity} · {item.price_mode === 'manual' ? t('accounts.investment.manualPrice') : t('accounts.investment.autoPrice')}</div>
            </div>
            <div className="text-right">
              <Amount value={item.market_value} currency={item.currency} showCurrency bold size="sm" />
              <div className={item.daily_pnl >= 0 ? 'text-xs text-emerald-600' : 'text-xs text-rose-600'}>{item.daily_pnl >= 0 ? '+' : ''}{item.daily_pnl.toFixed(2)}</div>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
