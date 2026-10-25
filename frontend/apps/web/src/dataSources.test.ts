import { afterEach, describe, expect, it, vi } from 'vitest'
import { createDataSource, fetchDataSources, syncDataSource, updateDataSource, deleteDataSource, fetchSourceSchema, ingestDataSource } from '@beecount/api-client'
import { parseRoute, routePath } from './state/router'

afterEach(() => vi.unstubAllGlobals())
const mockResponse = (data: unknown) => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}
describe('data sources integration contract', () => {
  it('uses a global route without changing finance or account routes', () => {
    expect(parseRoute('/app/data-sources')).toEqual({ kind: 'app', ledgerId: '', section: 'data-sources' })
    expect(routePath({ kind: 'app', ledgerId: '', section: 'data-sources' })).toBe('/app/data-sources')
    expect(routePath({ kind: 'app', ledgerId: '', section: 'accounts' })).toBe('/app/accounts')
    expect(routePath({ kind: 'app', ledgerId: '', section: 'finance' })).toBe('/app/finance')
  })
  it('preserves decimal strings and unknown modules instead of inventing zeros', async () => {
    const data = { items: [{ balances: [{ balance: '0.000000000000000001' }], net_equity: null, modules: [{ id: 'funding', status: 'unknown' }] }] }
    const fetch = mockResponse(data)
    expect(await fetchDataSources('test')).toEqual(data)
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/data-sources')
  })
  it('does not send blank credentials when editing only scheduling', async () => {
    const fetch = mockResponse({})
    await updateDataSource('test', 'source/id', { poll_interval_seconds: 600, paused: true })
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/data-sources/source%2Fid')
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ poll_interval_seconds: 600, paused: true })
    expect(fetch.mock.calls[0][1].method).toBe('PATCH')
  })
  it('sends explicit binding and read-only provider on create', async () => {
    const fetch = mockResponse({})
    await createDataSource('test', { name: 'Binance', provider: 'binance_api', credentials: { api_key: 'key', api_secret: 'secret' }, account_id: 'account-1', coverage_policy: 'replace_bound_account', poll_interval_seconds: 300, paused: false })
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ provider: 'binance_api', account_id: 'account-1', coverage_policy: 'replace_bound_account' })
  })
  it('creates a normalized JSON connection without exchange credentials', async () => {
    const fetch = mockResponse({})
    await createDataSource('test', { name: 'CLI import', provider: 'normalized_json', account_id: null, coverage_policy: 'separate', poll_interval_seconds: 300, paused: false })
    const body = JSON.parse(fetch.mock.calls[0][1].body)
    expect(body.provider).toBe('normalized_json')
    expect(body).not.toHaveProperty('credentials')
  })
  it('loads the server schema and uploads normalized JSON without altering decimal strings', async () => {
    const schemaFetch = mockResponse({ type: 'object' })
    expect(await fetchSourceSchema('test')).toEqual({ type: 'object' })
    expect(schemaFetch.mock.calls[0][0]).toBe('/api/v1/data-sources/schema')
    const uploadFetch = mockResponse({})
    const body = { balances: [{ balance: '0.000000000000000001' }] }
    await ingestDataSource('test', 'source/id', body, 'upload-retry')
    expect(uploadFetch.mock.calls[0][0]).toBe('/api/v1/data-sources/source%2Fid/ingest')
    expect(JSON.parse(uploadFetch.mock.calls[0][1].body)).toEqual(body)
    expect(uploadFetch.mock.calls[0][1].headers['Idempotency-Key']).toBe('upload-retry')
  })
  it('uses idempotency keys for manual refresh and DELETE for removal', async () => {
    const fetch = mockResponse({})
    await syncDataSource('test', 'one', 'retry-key')
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/data-sources/one/sync')
    expect(fetch.mock.calls[0][1].headers['Idempotency-Key']).toBe('retry-key')
    mockResponse({ deleted: true })
    expect(await deleteDataSource('test', 'one')).toEqual({ deleted: true })
  })
})
