import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Button, Dialog, DialogContent, DialogTitle, Input, Label } from '@beecount/ui'
import { API_BASE } from '@beecount/api-client'
import { MAX_SOURCE_JSON_BYTES, parseSourceJson } from '../../lib/sourceJson'

type Props = { name: string; sourceId: string; paused: boolean; loadSchema: () => Promise<unknown>; upload: (body: Record<string, unknown>, key: string) => Promise<unknown>; onClose: () => void; onSaved: () => void }
export function SourceJsonImport({ name, sourceId, paused, loadSchema, upload, onClose, onSaved }: Props) {
  const [schema, setSchema] = useState<unknown>(null)
  const [schemaError, setSchemaError] = useState('')
  const [schemaLoading, setSchemaLoading] = useState(true)
  const [body, setBody] = useState<Record<string, unknown> | null>(null)
  const [fileName, setFileName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const pending = useRef<{ body: string; key: string } | null>(null)
  const selection = useRef(0)
  const getSchema = async () => {
    setSchemaLoading(true); setSchemaError('')
    try { setSchema(await loadSchema()) } catch (err) { setSchemaError(err instanceof Error ? err.message : '无法读取 schema') } finally { setSchemaLoading(false) }
  }
  useEffect(() => { void getSchema() }, [])
  const choose = async (file?: File) => {
    const id = ++selection.current
    setBody(null); setFileName(''); setError('')
    if (!file) return
    try {
      if (file.size > MAX_SOURCE_JSON_BYTES) throw new Error('文件不能超过 2 MiB。请拆分或缩减导出数据。')
      const value = parseSourceJson(await file.text())
      if (id !== selection.current) return
      setBody(value); setFileName(file.name)
    } catch (err) { if (id === selection.current) setError(err instanceof Error ? err.message : '无法读取文件') }
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!body || paused) return
    setBusy(true); setError('')
    try {
      const serialized = JSON.stringify(body)
      if (pending.current?.body !== serialized) pending.current = { body: serialized, key: crypto.randomUUID() }
      await upload(body, pending.current.key)
      pending.current = null; onSaved()
    } catch (err) { setError(err instanceof Error ? err.message : '上传失败，请重试') } finally { setBusy(false) }
  }
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose() }}><DialogContent aria-describedby={undefined} showCloseButton={false} className="max-h-[90dvh] max-w-2xl overflow-y-auto rounded-3xl"><DialogTitle>导入标准 JSON · {name}</DialogTitle><p className="text-sm text-muted-foreground">云端只验证和接收标准 JSON，不执行 CLI 命令。必须先将 CLI 原始输出转换为下面的 schema；不要上传交易所密钥。导入将更新该连接的资产快照，可能改变绑定账户的汇总结果。</p>
    <details className="rounded-xl border border-border/60" open><summary className="cursor-pointer p-3 text-sm font-medium">查看服务端 schema</summary><div className="px-3 pb-3">{schemaLoading ? <p role="status" className="text-xs">正在读取…</p> : schemaError ? <p role="alert" className="text-xs text-destructive">{schemaError}<Button size="sm" variant="ghost" onClick={() => void getSchema()}>重试</Button></p> : <pre className="max-h-56 overflow-auto rounded-xl bg-muted/40 p-3 text-xs">{JSON.stringify(schema, null, 2)}</pre>}</div></details>
    <p className="break-all rounded-xl bg-muted/40 p-3 text-xs">外部定时上传目标：POST {API_BASE}/data-sources/{encodeURIComponent(sourceId)}/ingest。使用 BeeCount 身份认证及写权限；请在你控制的运行环境配置脚本和调度，不要把访问令牌写进上传文件。页面不会代为启动定时任务。</p>
    {paused && <p role="alert" className="rounded-xl bg-destructive/5 p-3 text-sm text-destructive">此连接已暂停接收上传。请关闭窗口，在连接卡片上点击「恢复接收上传」后再导入；仍可查看 schema。</p>}
    <form className="space-y-4" onSubmit={submit}><div className="space-y-2"><Label htmlFor="source-json-file">JSON 文件（最多 2 MiB）</Label><Input id="source-json-file" type="file" accept="application/json,.json" disabled={busy} onChange={(e) => void choose(e.target.files?.[0])} /></div>{fileName && <p role="status" className="text-sm">已读取：{fileName}。最终字段与时间有效性由服务端校验；金额应使用十进制字符串。</p>}{error && <p role="alert" className="break-words rounded-xl bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}<div className="flex justify-end gap-2"><Button type="button" variant="outline" disabled={busy} onClick={onClose}>取消</Button><Button type="submit" disabled={paused || busy || !body || schemaLoading || !!schemaError}>{busy ? '正在导入…' : '确认导入'}</Button></div></form>
  </DialogContent></Dialog>
}
