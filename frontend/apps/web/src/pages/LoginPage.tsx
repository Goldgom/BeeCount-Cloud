import { FormEvent, useEffect, useState } from 'react'
import { HelpCircle, X } from 'lucide-react'

import {
  ApiError,
  detectWebClientInfo,
  getStoredDeviceId,
  login,
  verifyTwoFA
} from '@beecount/api-client'
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Button,
  Input,
  Label,
  LanguageToggle,
  ThemeToggle,
  useT
} from '@beecount/ui'
import { localizeError } from '../i18n/errors'

const HINT_DISMISSED_KEY = 'login_initial_password_hint_dismissed'

type LoginPageProps = {
  onLoggedIn: (token: string) => void
}

type ChallengeState = {
  challenge_token: string
  available_methods: Array<'totp' | 'recovery_code'>
}

export function LoginPage({ onLoggedIn }: LoginPageProps) {
  const t = useT()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [notice, setNotice] = useState<{ type: 'default' | 'destructive'; title: string; message: string } | null>(null)
  const [challenge, setChallenge] = useState<ChallengeState | null>(null)

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setLoading(true)
    try {
      const data = await login(email, password)
      if (data.requires_2fa && data.challenge_token) {
        // 切到 2FA 输码视图,留住表单内容(用户失败重试时不必重输邮密)
        setChallenge({
          challenge_token: data.challenge_token,
          available_methods: data.available_methods || ['totp', 'recovery_code']
        })
        setNotice(null)
        return
      }
      if (data.access_token) {
        onLoggedIn(data.access_token)
        setNotice(null)
      }
    } catch (err) {
      const message = localizeError(err, t)
      if (err instanceof ApiError && err.code === 'AUTH_INVALID_CREDENTIALS') {
        setNotice({
          type: 'destructive',
          title: t('notice.failed'),
          message: t('login.error.invalid')
        })
        return
      }
      setNotice({
        type: 'destructive',
        title: t('notice.failed'),
        message
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-background text-foreground">
      {/* 右上角工具栏 */}
      <div className="absolute right-4 top-4 flex items-center gap-2">
        <LanguageToggle />
        <ThemeToggle />
      </div>

      <div className="relative mx-auto flex min-h-screen w-full max-w-md items-center justify-center px-4 py-10">
        <div className="w-full">
          {/* 右：登录表单卡 */}
          <div className="w-full">
            <div className="rounded-2xl border border-border/60 bg-card p-8 shadow-sm">
              <div className="mb-8 space-y-5">
                <img src="/branding/logo.svg" alt="" className="h-12 w-12" />
                <div><h1 className="text-2xl font-semibold tracking-tight">BeeCount Cloud</h1><p className="mt-2 text-sm text-muted-foreground">{t('login.submit')}</p></div>
              </div>

              {challenge ? (
                <TwoFactorChallengeView
                  challenge={challenge}
                  onCancel={() => {
                    setChallenge(null)
                    setNotice(null)
                  }}
                  onVerified={(accessToken) => {
                    onLoggedIn(accessToken)
                  }}
                />
              ) : (
                <form className="space-y-4" onSubmit={onSubmit}>
                  <div className="space-y-1.5">
                    <Label htmlFor="login-email">{t('login.email')}</Label>
                    <Input
                      id="login-email"
                      autoComplete="email"
                      placeholder="owner@example.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor="login-password">{t('login.password')}</Label>
                      {/* (?) 图标 hover 出 hint —— 即便用户关掉了下方提示卡,仍
                          能从这里查到初始密码出处。Tooltip 仅是 native title,
                          需要包裹 button(span 上的 title 在某些浏览器里 SVG
                          区域不触发 hover);同时点击 toggle 出可见浮窗作为
                          兜底,移动端 / 触屏没有 hover 时也能查看。 */}
                      <PasswordHintTrigger />
                    </div>
                    <Input
                      id="login-password"
                      type="password"
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </div>
                  {/* 初次部署的用户经常不知道初始密码哪里来 — 自部署 server 在
                      首次启动时会把 admin 账号 + 密码打到 docker log,同时
                      也写入容器内 `var/initial_admin_password` 文件。提示卡
                      显示在密码框下方,带 × 关闭按钮,关闭后写 localStorage,
                      下次不再显示。 */}
                  <InitialPasswordHint />
                  <Button className="w-full" type="submit" disabled={loading}>
                    {loading ? '…' : t('login.submit')}
                  </Button>
                </form>
              )}

              {notice && (
                <Alert className="mt-4" variant={notice.type}>
                  <AlertTitle>{notice.title}</AlertTitle>
                  <AlertDescription>{notice.message}</AlertDescription>
                </Alert>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * (?) 图标 — hover 显示 native title;点击 toggle 一个临时浮窗,移动端没
 * hover 也能看;再点别处 / 自身关闭。比 Tooltip 组件可靠,因为后者只是 span
 * 的 title 在 SVG hit area 上某些浏览器不一定触发。
 */
function PasswordHintTrigger() {
  const t = useT()
  const [open, setOpen] = useState(false)
  const hint = t('login.initialPasswordHint') as string

  // 点弹窗外部 / Esc 关闭
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const onDoc = () => setOpen(false)
    window.addEventListener('keydown', onKey)
    // 用 setTimeout + capture=false,避免本次点击直接被 onDoc 捕获关掉
    const tid = window.setTimeout(() => document.addEventListener('click', onDoc), 0)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('click', onDoc)
      window.clearTimeout(tid)
    }
  }, [open])

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        title={hint}
        aria-label={hint}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
        className="rounded-full p-0.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>
      {open ? (
        <span
          role="tooltip"
          onClick={(e) => e.stopPropagation()}
          className="absolute left-1/2 top-full z-10 mt-1.5 w-[280px] -translate-x-1/2 rounded-md border border-border/60 bg-popover px-3 py-2 text-[11px] leading-relaxed text-foreground shadow-lg"
        >
          {hint}
        </span>
      ) : null}
    </span>
  )
}

/**
 * 初始密码引导 —— 自部署 server 首次启动时,admin 账号 + 密码会:
 *  1) 打到 docker-compose / docker logs 输出
 *  2) 写到容器 `var/initial_admin_password` 文件
 *
 * 很多用户初次访问 web 不知道这件事,反复来问"哪里注册"。这条提示只显示
 * 在登录态(2FA challenge 切走后不显示),× 关闭后写 localStorage,下次
 * 访问不再展示。即便关掉,密码 label 旁的 (?) 图标 hover 仍能看见同款
 * 文案,信息不会彻底丢失。
 */
function InitialPasswordHint() {
  const t = useT()
  const [dismissed, setDismissed] = useState(true)

  useEffect(() => {
    if (typeof window === 'undefined') return
    setDismissed(window.localStorage.getItem(HINT_DISMISSED_KEY) === '1')
  }, [])

  if (dismissed) return null

  const close = () => {
    setDismissed(true)
    try {
      window.localStorage.setItem(HINT_DISMISSED_KEY, '1')
    } catch {
      // 用户禁了 localStorage —— 本次会话内消失也算
    }
  }

  return (
    <div className="relative rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 pr-8 text-[11px] leading-relaxed text-foreground">
      <button
        type="button"
        onClick={close}
        className="absolute right-1.5 top-1.5 rounded p-0.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
        aria-label={t('common.close') as string}
      >
        <X className="h-3 w-3" />
      </button>
      {t('login.initialPasswordHint')}
    </div>
  )
}

/**
 * 2FA challenge view - login 拿到 requires_2fa=true 后切到这个表单。
 *
 * 倒计时:5 分钟从 challenge_token 签发起算;到点提示用户重新登录(后端的
 * challenge_token 实际 exp 也是 5 分钟,这里只是 UI 提示,过期后 verify 会
 * 抛 401,我们 fallback 让用户重 login)。
 */
function TwoFactorChallengeView({
  challenge,
  onCancel,
  onVerified
}: {
  challenge: ChallengeState
  onCancel: () => void
  onVerified: (accessToken: string) => void
}) {
  const t = useT()
  const [method, setMethod] = useState<'totp' | 'recovery_code'>('totp')
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setLoading(true)
    setErr(null)
    try {
      const data = await verifyTwoFA({
        challenge_token: challenge.challenge_token,
        method,
        code: code.trim().replace(/\s+/g, ''),
        device_id: getStoredDeviceId(),
        client_info: detectWebClientInfo()
      })
      if (data.access_token) {
        onVerified(data.access_token)
      }
    } catch (e) {
      const message = e instanceof ApiError ? e.message : String(e)
      setErr(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className="space-y-4" onSubmit={onSubmit}>
      <div className="space-y-1.5">
        <Label>{t('login.twofa.method')}</Label>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant={method === 'totp' ? 'default' : 'outline'}
            onClick={() => {
              setMethod('totp')
              setCode('')
            }}
          >
            {t('login.twofa.methodTotp')}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={method === 'recovery_code' ? 'default' : 'outline'}
            onClick={() => {
              setMethod('recovery_code')
              setCode('')
            }}
          >
            {t('login.twofa.methodRecovery')}
          </Button>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="login-2fa-code">
          {method === 'totp' ? t('login.twofa.totpLabel') : t('login.twofa.recoveryLabel')}
        </Label>
        <Input
          id="login-2fa-code"
          inputMode={method === 'totp' ? 'numeric' : 'text'}
          autoComplete="one-time-code"
          maxLength={method === 'totp' ? 6 : 16}
          placeholder={method === 'totp' ? '000000' : 'xxxx-xxxx'}
          value={code}
          onChange={(e) =>
            setCode(method === 'totp' ? e.target.value.replace(/\D/g, '') : e.target.value)
          }
          autoFocus
        />
      </div>
      {err && <p className="text-sm text-destructive">{err}</p>}
      <div className="flex gap-2">
        <Button type="button" variant="outline" onClick={onCancel} className="flex-1">
          {t('common.cancel')}
        </Button>
        <Button
          type="submit"
          disabled={loading || (method === 'totp' ? code.length !== 6 : code.length < 6)}
          className="flex-1"
        >
          {loading ? '…' : t('login.twofa.submit')}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t('login.twofa.hint')}</p>
    </form>
  )
}
