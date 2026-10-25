import { authedGet, authedPost } from './http'

export type FinanceBalance = { account_id: string; account_name: string; currency: string; cash_balance: number; balance_decimal: string; cash_as_of: string }
export type FinanceEvent = { id: string; kind: string; effective_at: string; created_at: string; payload: Record<string, string>; effects: Record<string, string> }
export type Receivable = FinanceEvent & { paid: string; remaining: string; installments: (FinanceEvent & { paid: string; remaining: string })[]; repayments: FinanceEvent[] }
export const fetchFinanceBalances = (token: string) => authedGet<Record<string, FinanceBalance>>('/finance/balances', token)
export const fetchFinanceEvents = (token: string) => authedGet<FinanceEvent[]>('/finance/events', token)
export const fetchReceivables = (token: string) => authedGet<Receivable[]>('/finance/receivables', token)
export const postFinanceEvent = (token: string, kind: string, data: Record<string, string>, key: string) => authedPost<FinanceEvent>('/finance/events', token, { kind, data }, key)
