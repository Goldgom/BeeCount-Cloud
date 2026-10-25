import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Database, Plus, RefreshCw, ShieldCheck, AlertTriangle, X } from 'lucide-react'
import { createDataSource, deleteDataSource, fetchDataSources, fetchSourceAccounts, fetchSourceProviders, fetchSourceSchema, ingestDataSource, syncDataSource, updateDataSource, type DataSource, type SourceAccount, type SourceInput, type SourceProvider } from '@beecount/api-client'
import { Button, Card, CardContent, CardHeader, CardTitle, Input, Label, Dialog, DialogContent, DialogTitle } from '@beecount/ui'
import { useAuth } from '../../context/AuthContext'
import { SourceJsonImport } from './SourceJsonImport'

const moduleNames: Record<string, string> = { spot: '现货', funding: '资金账户', earn_flexible: '活期理财', portfolio_margin: '统一账户', usd_m_futures: 'U 本位合约', coin_m_futures: '币本位合约' }
const statusNames = { never_synced: '尚未同步', ok: '覆盖完整', partial: '部分覆盖', error: '同步失败' }
const time = (value: string | null | undefined) => value ? new Date(value).toLocaleString() : '—'
const failure = (err: unknown) => err instanceof Error ? err.message : '请求失败，请重试'
const selectClass = 'h-10 w-full rounded-xl border border-input bg-card px-3 text-sm'

export function DataSourcesPage() {
  const { token } = useAuth()
  const [sources, setSources] = useState<DataSource[]>([])
  const [providers, setProviders] = useState<SourceProvider[]>([])
  const [accounts, setAccounts] = useState<SourceAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editor, setEditor] = useState<DataSource | 'new' | null>(null)
  const [deleting, setDeleting] = useState<DataSource | null>(null)
  const [notice, setNotice] = useState('')
  const [importing, setImporting] = useState<DataSource | null>(null)
  const syncKeys = useRef(new Map<string, string>())
  const refresh = useCallback(async () => {
    try {
      const [s, p, a] = await Promise.all([fetchDataSources(token), fetchSourceProviders(token), fetchSourceAccounts(token)])
      setSources(s.items); setProviders(p.items); setAccounts(a.items); setError('')
    } catch (err) { setError(failure(err)) } finally { setLoading(false) }
  }, [token])
  useEffect(() => {
    void refresh()
    // This only reads server state. The backend scheduler owns actual provider polling.
    const timer = window.setInterval(() => { if (!document.hidden) void refresh() }, 15000)
    return () => window.clearInterval(timer)
  }, [refresh])
  const act = async (operation: () => Promise<unknown>, message: string) => {
    setBusy(true); setError(''); setNotice('')
    try { await operation(); setNotice(message); await refresh() } catch (err) { setError(failure(err)) } finally { setBusy(false) }
  }
  const manualSync = (s: DataSource) => act(async () => {
    let key = syncKeys.current.get(s.id)
    if (!key) { key = crypto.randomUUID(); syncKeys.current.set(s.id, key) }
    await syncDataSource(token, s.id, key)
    syncKeys.current.delete(s.id)
  }, '刷新请求已完成，请查看模块覆盖状态；部分覆盖不代表完整资产。')

  return <div className="space-y-6">
    <div className="bc-page-heading"><div><h1>数据源</h1><p>只读连接，清晰掌握资产从哪里来。</p></div><Button disabled={busy || loading || !providers.some((p) => p.available)} onClick={() => setEditor('new')}><Plus size={16} className="mr-2" />新建连接</Button></div>
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-border/60 bg-card p-4 text-sm"><ShieldCheck className="shrink-0 text-primary" size={22} /><p className="flex-1">优先使用币安官方只读 API：权限可控、行为可审计，比不受控的 shell CLI 更安全。请关闭交易、提现与划转权限，并配置 IP 白名单。</p><Link className="text-primary" to="/app/accounts">管理 BeeCount 账户 →</Link></div>
    {error && <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm">{error}<Button variant="ghost" size="sm" disabled={busy} onClick={() => void refresh()}>重新加载</Button></div>}
    {notice && <p role="status" className="rounded-xl bg-primary/5 p-3 text-sm">{notice}</p>}
    <p className="text-xs text-muted-foreground">官方 API 由服务端按间隔刷新，非 WebSocket 推送；标准 JSON 连接由外部上传更新。此页面每 15 秒读取最新状态。{providers.filter((p) => !p.available).map((p) => <span key={p.id}> {p.name} 暂不可用{p.reason ? `：${p.reason}` : '。'}</span>)}</p>
    {loading ? <p role="status" className="py-12 text-center text-muted-foreground">正在读取连接…</p> : !sources.length && !error ? <Card><CardContent className="flex flex-col items-center gap-3 py-14 text-center"><Database className="text-muted-foreground" size={36} /><h2 className="text-lg font-semibold">还没有数据源</h2><p className="max-w-md text-sm text-muted-foreground">连接币安后查看各账户模块的真实覆盖状态。未覆盖的账户不会被当成零余额。</p><Button disabled={!providers.some((p) => p.available)} onClick={() => setEditor('new')}>连接币安</Button></CardContent></Card> : null}
    {sources.map((s) => {
      const unknown = s.modules.filter((m) => m.status !== 'ok')
      return <Card key={s.id}>
        <CardHeader><div className="flex flex-wrap items-start justify-between gap-4"><div><CardTitle>{s.name}</CardTitle><p className="mt-2 text-xs text-muted-foreground">{providers.find((p) => p.id === s.provider)?.name || s.provider} · {s.provider === 'normalized_json' ? '外部标准 JSON 上传 · 云端不执行命令' : s.credentials_configured ? '凭据已配置（不回显）' : '未配置凭据'}</p></div><div className="flex flex-wrap gap-2 text-xs"><span className={`rounded-full px-3 py-1 ${s.status === 'ok' && !s.stale ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'}`}>{statusNames[s.status]}</span>{s.stale && <span className="rounded-full bg-destructive/10 px-3 py-1 text-destructive">数据陈旧</span>}{s.paused && <span className="rounded-full bg-muted px-3 py-1">{s.provider === 'normalized_json' ? '已暂停接收上传' : '已暂停自动刷新'}</span>}</div></div></CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 rounded-2xl bg-muted/40 p-4 sm:grid-cols-3"><div><p className="text-xs text-muted-foreground">{s.net_equity == null ? '已知部分估值 · 非资产总额' : '净权益估值'}</p><p className="mt-1 break-all font-mono text-xl font-semibold">{s.net_equity ?? s.known_net_equity ?? '—'} <span className="text-xs">{s.valuation_currency || 'USDT'}</span></p></div><div><p className="text-xs text-muted-foreground">上次成功</p><p className="mt-2 text-sm">{time(s.last_success_at)}</p></div><div><p className="text-xs text-muted-foreground">自动刷新</p><p className="mt-2 text-sm">{s.provider === 'normalized_json' ? s.paused ? '已暂停接收上传' : '等待外部上传' : s.paused ? '已暂停' : `每 ${s.poll_interval_seconds} 秒`}</p><p className="mt-1 text-xs text-muted-foreground">下一次：{s.provider === 'normalized_json' || s.paused ? '—' : time(s.next_sync_at)}</p></div></div>
          {s.pm_equity && <div className="rounded-xl border border-border/60 p-3 text-sm"><p className="font-medium">统一账户原币权益</p><p className="mt-1 break-all font-mono">{s.pm_equity.amount} {s.pm_equity.currency}</p><p className="mt-1 text-xs text-muted-foreground">{time(s.pm_equity.source_time)} · 保留原始计价，不将 USD 假定为 USDT，也不与其他模块直接相加。</p></div>}
          <div className="text-sm"><span className="font-medium">汇总边界：</span>{s.account_id ? <>替代绑定账户「{accounts.find((a) => a.id === s.account_id)?.name || s.account_id}」的手工资产，避免重复汇总；不改写账户余额。</> : '独立数据源，未绑定 BeeCount 账户。若已有同一笔手工资产，请编辑连接并显式绑定，避免重复汇总。'}</div>
          {s.error && <p role="alert" className="break-words rounded-xl bg-destructive/5 p-3 text-sm text-destructive">{s.error}</p>}
          <div><h3 className="mb-3 text-sm font-semibold">账户模块覆盖</h3>{!s.modules.length ? <p className="text-sm text-muted-foreground">尚无模块结果。首次刷新前，所有模块覆盖均未知。</p> : <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{s.modules.map((m) => <div key={m.id} className="rounded-xl border border-border/60 p-3"><p className="flex justify-between gap-2 text-sm"><span>{moduleNames[m.id] || m.id}</span><span className={m.status === 'ok' ? 'text-primary' : 'text-destructive'}>{m.status === 'ok' ? '已覆盖' : '未覆盖 / 未知'}</span></p><p className="mt-1 text-xs text-muted-foreground">{m.status === 'ok' ? time(m.source_time) : m.error || '尚未获得数据，不计为零'}</p></div>)}</div>}</div>
          {(unknown.length > 0 || s.status === 'partial') && <div className="rounded-xl bg-muted/50 p-3 text-sm"><p className="flex items-center gap-2 font-medium"><AlertTriangle size={16} />未覆盖清单</p><p className="mt-1">{unknown.length ? unknown.map((m) => moduleNames[m.id] || m.id).join('、') : '后端标记为部分覆盖，请检查错误详情。'}。这里只展示已知部分，不能视为完整总资产。</p></div>}
          <details className="rounded-xl border border-border/60"><summary className="cursor-pointer p-4 text-sm font-medium">原币余额与持仓 · 保留原始精度</summary><div className="space-y-4 px-4 pb-4"><p className="text-xs text-muted-foreground">数据时间：{time(s.source_time)} · 估值日期：{s.valuation_date || '—'} · 最近尝试：{time(s.last_attempt_at)}。金额直接显示服务端十进制字符串，不转换浮点数。</p><div className="overflow-x-auto"><table className="w-full whitespace-nowrap text-left text-xs"><caption className="sr-only">原币精确余额</caption><thead><tr className="border-b border-border"><th className="p-2">模块 / 币种</th><th className="p-2">余额</th><th className="p-2">可用</th><th className="p-2">净权益</th><th className="p-2">未实现盈亏</th><th className="p-2">估值 USDT</th><th className="p-2">数据时间</th></tr></thead><tbody>{s.balances.map((b, i) => <tr key={`${b.module}-${b.asset}-${i}`} className="border-b border-border/40"><td className="p-2">{moduleNames[b.module] || b.module} / {b.asset}</td><td className="p-2 font-mono">{b.balance}</td><td className="p-2 font-mono">{b.available ?? '—'}</td><td className="p-2 font-mono">{b.net_equity ?? '—'}</td><td className="p-2 font-mono">{b.unrealized_pnl ?? '—'}</td><td className="p-2 font-mono">{b.value_usdt ?? '未估值'}</td><td className="p-2">{time(b.source_time)}</td></tr>)}</tbody></table>{!s.balances.length && <p className="py-4 text-sm text-muted-foreground">暂无余额记录；不代表账户余额为零。</p>}</div>{s.positions.length > 0 && <div className="overflow-x-auto"><table className="w-full whitespace-nowrap text-left text-xs"><caption className="pb-2 text-left font-medium">合约持仓（原始精度）</caption><thead><tr><th className="p-2">模块 / 合约</th><th className="p-2">数量</th><th className="p-2">名义价值</th><th className="p-2">未实现盈亏</th></tr></thead><tbody>{s.positions.map((p, i) => <tr key={`${p.module}-${p.symbol}-${i}`}><td className="p-2">{moduleNames[p.module] || p.module} / {p.symbol}</td><td className="p-2 font-mono">{p.quantity}</td><td className="p-2 font-mono">{p.notional ?? '—'}</td><td className="p-2 font-mono">{p.unrealized_pnl ?? '—'}</td></tr>)}</tbody></table></div>}</div></details>
          <div className="flex flex-wrap gap-2">{s.provider === 'normalized_json' ? <><Button variant="outline" disabled={busy} onClick={() => setImporting(s)}>导入 JSON / 查看 schema</Button><Button variant="outline" disabled={busy} onClick={() => void act(() => updateDataSource(token, s.id, { paused: !s.paused }), s.paused ? '已恢复接收上传' : '已暂停接收上传；后续导入将被拒绝')}>{s.paused ? '恢复接收上传' : '暂停接收上传'}</Button></> : <><Button variant="outline" disabled={busy} onClick={() => void manualSync(s)}><RefreshCw size={15} className="mr-2" />手动刷新</Button><Button variant="outline" disabled={busy} onClick={() => void act(() => updateDataSource(token, s.id, { paused: !s.paused }), s.paused ? '自动刷新已恢复' : '自动刷新已暂停；仍可手动刷新')}>{s.paused ? '恢复自动刷新' : '暂停自动刷新'}</Button></>}<Button variant="ghost" disabled={busy} onClick={() => setEditor(s)}>编辑连接</Button><Button variant="ghost" className="text-destructive" disabled={busy} onClick={() => setDeleting(s)}>删除</Button></div>
        </CardContent>
      </Card>
    })}
    {importing && <SourceJsonImport name={importing.name} sourceId={importing.id} paused={importing.paused} loadSchema={() => fetchSourceSchema(token)} upload={(body, key) => ingestDataSource(token, importing.id, body, key)} onClose={() => setImporting(null)} onSaved={() => { setImporting(null); setNotice('标准 JSON 已导入，请查看覆盖状态和最新数据时间。'); void refresh() }} />}
    {editor && <SourceEditor key={typeof editor === 'string' ? editor : editor.id} source={editor === 'new' ? null : editor} providers={providers} accounts={accounts} token={token} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); setNotice('连接已保存。请检查首次刷新后的模块覆盖状态。'); void refresh() }} />}
    {deleting && <Dialog open onOpenChange={(open) => { if (!open && !busy) setDeleting(null) }}><DialogContent showCloseButton={false} aria-describedby={undefined} className="max-w-md rounded-3xl"><DialogTitle>删除「{deleting.name}」？</DialogTitle><p className="my-4 text-sm text-muted-foreground">将移除此连接及其凭据，停止后续刷新。删除后汇总边界会变化；绑定账户的手工资产将重新参与汇总。不会删除 BeeCount 账户。</p><div className="flex justify-end gap-2"><Button autoFocus variant="outline" disabled={busy} onClick={() => setDeleting(null)}>取消</Button><Button className="bg-destructive text-destructive-foreground" disabled={busy} onClick={() => void act(async () => { await deleteDataSource(token, deleting.id); setDeleting(null) }, '连接已删除')}>确认删除</Button></div></DialogContent></Dialog>}
  </div>
}

function SourceEditor({ source, providers, accounts, token, onClose, onSaved }: { source: DataSource | null; providers: SourceProvider[]; accounts: SourceAccount[]; token: string; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(source?.name || '')
  const [provider, setProvider] = useState(source?.provider || providers.find((p) => p.id === 'binance_api' && p.available)?.id || providers.find((p) => p.available)?.id || '')
  const [accountId, setAccountId] = useState(source?.account_id || '')
  const [interval, setInterval] = useState(String(source?.poll_interval_seconds ?? 300))
  const [apiKey, setApiKey] = useState('')
  const [secret, setSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    try {
      if (provider === 'binance_api' && (apiKey || secret) && (!apiKey || !secret)) throw new Error('更换凭据时需要同时输入 API Key 和 Secret。')
      const body: SourceInput = { name: name.trim(), provider, account_id: accountId || null, coverage_policy: accountId ? 'replace_bound_account' : 'separate', poll_interval_seconds: Number(interval), paused: source?.paused ?? false }
      if (!body.name) throw new Error('请输入连接名称。')
      if (provider === 'binance_api' && apiKey && secret) body.credentials = { api_key: apiKey, api_secret: secret }
      if (source) await updateDataSource(token, source.id, body)
      else await createDataSource(token, body)
      setApiKey(''); setSecret(''); onSaved()
    } catch (err) { setError(failure(err)) } finally { setBusy(false) }
  }
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose() }}><DialogContent showCloseButton={false} aria-describedby={undefined} className="max-h-[90dvh] max-w-xl overflow-y-auto rounded-3xl"><div className="mb-5 flex items-center justify-between"><DialogTitle className="text-xl">{source ? '编辑连接' : '新建只读连接'}</DialogTitle><Button variant="ghost" size="icon" disabled={busy} aria-label="关闭" onClick={onClose}><X size={18} /></Button></div><form onSubmit={submit} className="space-y-4">
    {error && <p role="alert" className="rounded-xl bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
    <div className="space-y-2"><Label htmlFor="source-name">连接名称</Label><Input autoFocus id="source-name" maxLength={120} required value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：我的币安" /></div>
    <div className="space-y-2"><Label htmlFor="source-provider">数据提供方</Label><select id="source-provider" className={selectClass} disabled={!!source} required value={provider} onChange={(e) => { setProvider(e.target.value); setApiKey(''); setSecret('') }}>{providers.filter((p) => p.available || p.id === source?.provider).map((p) => <option value={p.id} key={p.id}>{p.name}</option>)}</select></div>
    {provider === 'normalized_json' ? <div className="rounded-2xl bg-muted/50 p-4 text-sm"><p className="font-medium">标准 JSON / CLI 适配</p><p className="mt-2 text-muted-foreground">云端不会执行 shell 或 CLI 命令，也不自动识别任意 CLI 原生输出。请在你控制的环境中将输出转换为服务端 schema，再导入文件或由外部脚本定时上传。不要在文件中包含 API 密钥。</p></div> : <fieldset className="space-y-3 rounded-2xl border border-border/60 p-4"><legend className="px-1 text-sm font-medium">{source ? '更换密钥（留空保留已有凭据）' : '只读 API 凭据'}</legend><p className="text-xs text-muted-foreground">不请求、不显示已有密钥。仅用于读取；不要启用交易、提现或划转权限。</p><div className="space-y-2"><Label htmlFor="source-api-key">API Key</Label><Input id="source-api-key" type="password" autoComplete="new-password" spellCheck={false} required={!source} value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></div><div className="space-y-2"><Label htmlFor="source-secret">API Secret</Label><Input id="source-secret" type="password" autoComplete="new-password" spellCheck={false} required={!source} value={secret} onChange={(e) => setSecret(e.target.value)} /></div></fieldset>}
    <div className="space-y-2"><Label htmlFor="source-account">显式绑定 BeeCount 账户</Label><select id="source-account" className={selectClass} value={accountId} onChange={(e) => setAccountId(e.target.value)}><option value="">独立数据源（不绑定）</option>{accounts.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.currency}</option>)}</select><p className="text-xs text-muted-foreground">{accountId ? '使用数据源替代此账户的手工现金及持仓汇总，防止双计。不写回账户余额。一个账户只能绑定一个连接。' : '若已在 BeeCount 记录同一平台资产，请选择对应账户，否则可能重复汇总。'}</p></div>
    <div className="space-y-2"><Label htmlFor="source-interval">{provider === 'normalized_json' ? '预期更新间隔（秒）' : '自动刷新间隔（秒）'}</Label><Input id="source-interval" type="number" required min={60} max={86400} step={1} value={interval} onChange={(e) => setInterval(e.target.value)} /><p className="text-xs text-muted-foreground">{provider === 'normalized_json' ? '不启用云端轮询。此间隔仅用于识别数据陈旧；自动更新需在外部脚本环境配置定时上传。' : '60–86400 秒；由服务端调度，可能受币安限流及权限影响。'}</p></div>
    <div className="flex justify-end gap-2 pt-2"><Button type="button" variant="outline" disabled={busy} onClick={onClose}>取消</Button><Button type="submit" disabled={busy || !provider}>{busy ? '正在保存…' : '保存连接'}</Button></div>
  </form></DialogContent></Dialog>
}
