import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { fetchFinanceBalances, fetchFinanceEvents, fetchReceivables, postFinanceEvent, type FinanceBalance, type FinanceEvent, type Receivable } from '@beecount/api-client'
import { Button, Card, CardContent, CardHeader, CardTitle, Input, Label, useT } from '@beecount/ui'
import { Amount } from '@beecount/web-features'
import { useAuth } from '../../context/AuthContext'
import { useSyncRefresh } from '../../context/SyncSocketContext'
import { localizeError } from '../../i18n/errors'

const kinds = ['reconciliation', 'transfer', 'receivable', 'receivable_installment', 'repayment'] as const
type Kind = typeof kinds[number]
export function FinancePage() {
  const t = useT()
  const { token } = useAuth()
  const [balances, setBalances] = useState<Record<string, FinanceBalance>>({})
  const [events, setEvents] = useState<FinanceEvent[]>([])
  const [receivables, setReceivables] = useState<Receivable[]>([])
  const [kind, setKind] = useState<Kind>('reconciliation')
  const [fields, setFields] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [result, setResult] = useState<FinanceEvent | null>(null)
  const pending = useRef<{ body: string; key: string } | null>(null)
  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [b, e, r] = await Promise.all([fetchFinanceBalances(token), fetchFinanceEvents(token), fetchReceivables(token)])
      setBalances(b); setEvents(e); setReceivables(r); setError('')
    } catch (err) { setError(localizeError(err, t)) } finally { setLoading(false) }
  }, [token, t])
  useEffect(() => { void refresh() }, [refresh])
  useSyncRefresh(() => { void refresh() })
  const field = (name: string, value: string) => setFields((prev) => ({ ...prev, [name]: value }))
  const account = balances[fields.account_id || '']
  const parent = receivables.find((r) => r.id === fields.receivable_id)
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(''); setResult(null)
    try {
      const data: Record<string, string> = { ...fields }
      if (kind === 'reconciliation') {
        if (!account) throw new Error(t('finance.selectAccount'))
        data.expected_balance = account.balance_decimal
        data.effective_at ||= new Date().toISOString()
        setFields((prev) => ({ ...prev, effective_at: data.effective_at }))
        data.source ||= 'web_manual'
      }
      if (kind === 'transfer') {
        data.from_currency = balances[data.from_account_id]?.currency || ''
        data.to_currency = balances[data.to_account_id]?.currency || ''
        data.source ||= 'web_manual'
        if (data.fee_amount && data.fee_amount !== '0') {
          data.fee_account_id = data.from_account_id
          data.fee_currency = data.from_currency
        }
      }
      if (kind === 'receivable') data.currency = (data.currency || 'CNY').toUpperCase()
      if (kind === 'receivable_installment') data.due_at = new Date(data.due_at).toISOString()
      if (!data.installment_id) delete data.installment_id
      const body = JSON.stringify({ kind, data })
      // Keep the same key on an unchanged retry after an uncertain network response.
      if (pending.current?.body !== body) pending.current = { body, key: crypto.randomUUID() }
      const receipt = await postFinanceEvent(token, kind, data, pending.current.key)
      pending.current = null; setResult(receipt); setFields({})
      await refresh()
    } catch (err) { setError(localizeError(err, t)) } finally { setBusy(false) }
  }
  const textField = (name: string, label: string, opts: { required?: boolean; type?: string; placeholder?: string } = {}) => <div className="space-y-2" key={name}><Label htmlFor={`finance-${name}`}>{label}</Label><Input id={`finance-${name}`} value={fields[name] || ''} onChange={(e) => field(name, e.target.value)} required={opts.required ?? true} type={opts.type || 'text'} placeholder={opts.placeholder} /></div>
  const select = (name: string, label: string, options: { value: string; label: string }[], required = true) => <div className="space-y-2" key={name}><Label htmlFor={`finance-${name}`}>{label}</Label><select id={`finance-${name}`} className="h-10 w-full rounded-xl border border-input bg-card px-3 text-sm" value={fields[name] || ''} required={required} onChange={(e) => field(name, e.target.value)}><option value="">—</option>{options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></div>
  const accountOptions = Object.values(balances).map((b) => ({ value: b.account_id, label: `${b.account_name} · ${b.currency}` }))
  return <div className="space-y-6">
    <div className="bc-page-heading"><div><h1>{t('finance.title')}</h1><p>{t('finance.subtitle')}</p></div><Link to="/app/accounts" className="text-sm text-primary">{t('nav.accounts')}</Link></div>
    {error ? <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm">{error}<Button variant="ghost" size="sm" onClick={() => void refresh()}>{t('finance.reload')}</Button></div> : null}
    {result ? <div role="status" className="rounded-xl border border-primary/30 bg-primary/5 p-4 text-sm"><p className="font-medium">{t('finance.recorded')}</p><p className="mt-1 break-all text-xs text-muted-foreground">{result.id}</p>{result.kind === 'reconciliation' ? <p className="mt-2">{result.payload.before_balance} → {result.payload.after_balance} {result.payload.currency} · Δ {result.payload.difference}</p> : null}</div> : null}
    <Card><CardHeader><CardTitle>{t('finance.operation')}</CardTitle></CardHeader><CardContent>
      <div className="bc-segmented mb-6 flex flex-wrap">{kinds.map((k) => <button type="button" key={k} aria-pressed={kind === k} onClick={() => { setKind(k); setFields({}); setResult(null) }}>{t(`finance.${k}`)}</button>)}</div>
      <form onSubmit={submit} className="grid gap-5 sm:grid-cols-2">
        {kind === 'reconciliation' ? <>{select('account_id', t('finance.account'), accountOptions)}{textField('target_balance', t('finance.targetBalance'), { placeholder: '0.00' })}<div className="rounded-xl bg-muted/50 p-4 text-sm sm:col-span-2">{t('finance.observedBalance')}: {account ? `${account.balance_decimal} ${account.currency}` : '—'}<p className="mt-1 text-xs text-muted-foreground">{t('finance.reconcileHint')}</p></div>{textField('source', t('finance.source'))}{textField('reason', t('finance.reason'))}</> : null}
        {kind === 'transfer' ? <>{select('from_account_id', t('finance.from'), accountOptions)}{select('to_account_id', t('finance.to'), accountOptions)}{textField('from_amount', t('finance.fromAmount'))}{textField('to_amount', t('finance.toAmount'))}{textField('external_id', t('finance.externalId'))}{textField('fee_amount', t('finance.fee'), { required: false, placeholder: '0.00' })}<p className="text-xs text-muted-foreground sm:col-span-2">{t('finance.transferHint')}</p></> : null}
        {kind === 'receivable' ? <>{textField('counterparty', t('finance.counterparty'))}{textField('amount', t('finance.amount'))}{textField('currency', t('finance.currency'), { placeholder: 'CNY' })}{textField('reason', t('finance.reason'))}</> : null}
        {kind === 'receivable_installment' || kind === 'repayment' ? <>{select('receivable_id', t('finance.receivable'), receivables.filter((r) => Number(r.remaining) > 0).map((r) => ({ value: r.id, label: `${r.payload.counterparty} · ${r.remaining} ${r.payload.currency}` })))}{textField('amount', t('finance.amount'))}{kind === 'receivable_installment' ? textField('due_at', t('finance.dueAt'), { type: 'datetime-local' }) : <>{select('account_id', t('finance.account'), accountOptions.filter((o) => !parent || balances[o.value].currency === parent.payload.currency))}{select('installment_id', t('finance.installmentOptional'), (parent?.installments || []).filter((i) => Number(i.remaining) > 0).map((i) => ({ value: i.id, label: `${i.payload.due_at} · ${i.remaining} ${i.payload.currency}` })), false)}</>}</> : null}
        <div className="flex items-center gap-3 sm:col-span-2"><Button type="submit" disabled={busy || loading}>{busy ? t('finance.saving') : t('finance.confirm')}</Button><span className="text-xs text-muted-foreground">{t('finance.auditHint')}</span></div>
      </form>
    </CardContent></Card>
    <div className="grid gap-6 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>{t('finance.receivables')}</CardTitle></CardHeader><CardContent><div className="divide-y divide-border/60">{receivables.length ? receivables.map((r) => <div key={r.id} className="py-4 first:pt-0"><div className="flex flex-wrap justify-between gap-2"><span className="font-medium">{r.payload.counterparty}</span><Amount value={Number(r.remaining)} currency={r.payload.currency} showCurrency compact={false} /></div><p className="mt-1 text-xs text-muted-foreground">{t('finance.paid')}: {r.paid} {r.payload.currency} · {r.payload.reason}</p>{r.installments.map((i) => <p key={i.id} className="mt-2 rounded-lg bg-muted/50 p-2 text-xs">{i.payload.due_at} · {t('finance.remaining')}: {i.remaining} {i.payload.currency}</p>)}</div>) : <p className="text-sm text-muted-foreground">{loading ? t('finance.loading') : t('finance.empty')}</p>}</div></CardContent></Card>
      <Card><CardHeader><CardTitle>{t('finance.journal')}</CardTitle></CardHeader><CardContent><div className="max-h-[480px] space-y-3 overflow-y-auto">{events.length ? events.slice().reverse().map((e) => <div key={e.id} className="rounded-xl bg-muted/40 p-3"><p className="text-sm font-medium">{t(`finance.${e.kind}`)}</p><p className="mt-1 break-all text-xs text-muted-foreground">{e.effective_at} · {e.id}</p>{Object.entries(e.effects).map(([id, value]) => <p key={id} className="mt-1 text-xs">{balances[id]?.account_name || id}: {value} {balances[id]?.currency}</p>)}</div>) : <p className="text-sm text-muted-foreground">{loading ? t('finance.loading') : t('finance.empty')}</p>}</div></CardContent></Card>
    </div>
  </div>
}
