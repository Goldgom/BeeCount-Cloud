import type { InvestmentHolding } from '@beecount/api-client'

export function investmentPnl(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return { value: null, tone: 'muted' as const }
  return { value, tone: value > 0 ? 'positive' as const : value < 0 ? 'negative' as const : 'default' as const }
}

/** Observation time is not the response generation time. Preserve source timezone. */
export function investmentObservation(item: Pick<InvestmentHolding, 'as_of' | 'snapshot_at' | 'price_updated_at'>): string | null {
  return item.as_of || item.snapshot_at || item.price_updated_at || null
}
