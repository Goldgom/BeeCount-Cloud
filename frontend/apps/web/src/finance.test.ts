import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchFinanceBalances, fetchReceivables, postFinanceEvent } from '@beecount/api-client'

afterEach(() => vi.unstubAllGlobals())
describe('finance API contracts', () => {
  it('posts exact decimal strings and reuses supplied idempotency key', async () => {
    const receipt = { id: 'event-1', kind: 'transfer', payload: {}, effects: {} }
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(receipt), { status: 200 }))
    vi.stubGlobal('fetch', fetcher)
    const data = { from_amount: '100.25', to_amount: '14.02', from_currency: 'CNY', to_currency: 'USD' }
    await postFinanceEvent('test-token', 'transfer', data, 'stable-retry-key')
    const [url, init] = fetcher.mock.calls[0]
    expect(url).toBe('/api/v1/finance/events')
    expect(init.headers['Idempotency-Key']).toBe('stable-retry-key')
    expect(init.headers.Authorization).toBe('Bearer test-token')
    expect(JSON.parse(init.body)).toEqual({ kind: 'transfer', data })
  })
  it('reads balance observations and receivables from their real endpoints', async () => {
    const fetcher = vi.fn().mockImplementation(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetcher)
    await fetchFinanceBalances('test-token')
    await fetchReceivables('test-token')
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/v1/finance/balances', '/api/v1/finance/receivables'])
  })
})
