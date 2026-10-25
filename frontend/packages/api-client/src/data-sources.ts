import { authedDelete, authedGet, authedPatch, authedPost } from './http'

export type SourceModule = { id: string; status: 'ok' | 'unknown'; error: string | null; source_time: string | null }
export type SourceBalance = { module: string; asset: string; balance: string; available: string | null; net_equity: string | null; unrealized_pnl: string | null; value_usdt: string | null; source_time: string | null }
export type SourcePosition = { module: string; symbol: string; quantity: string; notional: string | null; unrealized_pnl: string | null }
export type DataSource = {
  id: string; name: string; provider: string; account_id: string | null
  coverage_policy: 'replace_bound_account' | 'separate'; poll_interval_seconds: number; paused: boolean
  status: 'never_synced' | 'ok' | 'partial' | 'error'; last_attempt_at: string | null; last_success_at: string | null
  next_sync_at: string | null; stale: boolean; error: string | null; credentials_configured: boolean
  modules: SourceModule[]; balances: SourceBalance[]; positions: SourcePosition[]
  pm_equity?: { currency: string; amount: string; source_time: string | null } | null
  valuation_date?: string | null; source_time?: string | null; valuation_currency?: string; net_equity?: string | null; known_net_equity?: string
}
export type SourceProvider = { id: string; name: string; available: boolean; modules?: string[]; reason?: string }
export type SourceAccount = { id: string; name: string; currency: string }
export type SourceInput = { name: string; provider: string; credentials?: { api_key: string; api_secret: string }; account_id: string | null; coverage_policy: DataSource['coverage_policy']; poll_interval_seconds: number; paused: boolean }
const path = '/data-sources'
export const fetchDataSources = (token: string) => authedGet<{ items: DataSource[] }>(path, token)
export const fetchSourceProviders = (token: string) => authedGet<{ items: SourceProvider[] }>(`${path}/providers`, token)
export const fetchSourceAccounts = (token: string) => authedGet<{ items: SourceAccount[] }>(`${path}/accounts`, token)
export const createDataSource = (token: string, body: SourceInput) => authedPost<DataSource>(path, token, body)
export const updateDataSource = (token: string, id: string, body: Partial<SourceInput>) => authedPatch<DataSource>(`${path}/${encodeURIComponent(id)}`, token, body)
export const syncDataSource = (token: string, id: string, key: string) => authedPost<DataSource>(`${path}/${encodeURIComponent(id)}/sync`, token, {}, key)
export const fetchSourceSchema = (token: string) => authedGet<Record<string, unknown>>(`${path}/schema`, token)
export const ingestDataSource = (token: string, id: string, body: Record<string, unknown>, key: string) => authedPost<DataSource>(`${path}/${encodeURIComponent(id)}/ingest`, token, body, key)
export const deleteDataSource = (token: string, id: string) => authedDelete<{ deleted: boolean }>(`${path}/${encodeURIComponent(id)}`, token)
