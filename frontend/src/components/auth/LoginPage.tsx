/**
 * 登录页：设计迁移自 html/index.html（视觉保持原样）。
 * 变更点：忘记密码改为占位提示、固定布局禁滚动、品牌区去 logo 并左移、
 * 登录成功后整页淡出并与主应用淡入衔接。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { login as apiLogin, changePassword } from '../../api/auth'
import type { AuthRole, AuthUser } from '../../api/auth'
import { useAuth } from '../../store/AuthContext'
import '../../styles/login.css'

/** 身份切换的文案映射（保持原登录页设计） */
const ROLE_COPY: Record<AuthRole, { lede: string; cta: string; account: string }> = {
  student: { lede: '登录后继续练习与错题回顾', cta: '进入学习空间', account: '手机号或邮箱' },
  teacher: { lede: '登录后继续出题、组卷与发布', cta: '进入教师工作台', account: '工号、手机号或邮箱' },
}

interface FieldHint {
  text: string
  on: boolean
}

const EMPTY_HINT: FieldHint = { text: '', on: false }

export default function LoginPage() {
  const { signIn } = useAuth()

  const [role, setRole] = useState<AuthRole>('student')
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [accountHint, setAccountHint] = useState<FieldHint>(EMPTY_HINT)
  const [passwordHint, setPasswordHint] = useState<FieldHint>(EMPTY_HINT)
  const [status, setStatus] = useState<{ text: string; tone?: 'warn' | 'ok' } | null>(null)
  const [pwdOpen, setPwdOpen] = useState(false)
  const [pwdAccount, setPwdAccount] = useState('')
  const [pwdOld, setPwdOld] = useState('')
  const [pwdNew, setPwdNew] = useState('')
  const [pwdConfirm, setPwdConfirm] = useState('')
  const [pwdBusy, setPwdBusy] = useState(false)
  const [pwdStatus, setPwdStatus] = useState<{ text: string; tone?: 'warn' | 'ok' } | null>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const dustRef = useRef<HTMLCanvasElement>(null)

  // 登录页标题
  useEffect(() => {
    const prev = document.title
    document.title = '登录 · MathCraft 智能出题平台'
    return () => {
      document.title = prev
    }
  }, [])

  const resetField = useCallback((setter: React.Dispatch<React.SetStateAction<FieldHint>>) => {
    setter(EMPTY_HINT)
  }, [])

  /* ---------- 粒子层：移植自原登录页 initDust ---------- */
  useEffect(() => {
    const canvas = dustRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const makeSprite = (rgb: string) => {
      const size = 48
      const c = document.createElement('canvas')
      c.width = size
      c.height = size
      const g = c.getContext('2d')!
      const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
      grad.addColorStop(0, `rgba(${rgb},1)`)
      grad.addColorStop(0.32, `rgba(${rgb},0.62)`)
      grad.addColorStop(0.62, `rgba(${rgb},0.16)`)
      grad.addColorStop(1, `rgba(${rgb},0)`)
      g.fillStyle = grad
      g.fillRect(0, 0, size, size)
      return c
    }
    const spriteWhite = makeSprite('255,255,255')
    const spriteCyan = makeSprite('150,222,255')

    const rand = (min: number, max: number) => min + Math.random() * (max - min)
    let W = 0
    let H = 0
    type Particle = {
      x: number; y: number; r: number; vx: number; vy: number
      base: number; phase: number; speed: number; depth: number; cyan: boolean
    }
    let parts: Particle[] = []
    let rafId: number | null = null
    let running = false
    const pointer = { x: 0.5, y: 0.5, cx: 0.5, cy: 0.5 }

    const build = () => {
      let count = Math.round((W * H) / 15000)
      count = Math.max(34, Math.min(112, count))
      parts = []
      for (let i = 0; i < count; i++) {
        const isCyan = Math.random() < 0.3
        const bokeh = Math.random() < 0.1
        parts.push({
          x: rand(0, W), y: rand(0, H),
          r: bokeh ? rand(3, 5.4) : rand(0.8, isCyan ? 1.9 : 2.4),
          vx: rand(-0.1, 0.1) * (bokeh ? 0.5 : 1),
          vy: rand(-0.2, -0.04) * (bokeh ? 0.4 : 1),
          base: bokeh ? rand(0.08, 0.16) : rand(0.26, 0.68),
          phase: rand(0, Math.PI * 2),
          speed: rand(0.35, 1.05),
          depth: bokeh ? rand(0.6, 1) : rand(0.25, 1),
          cyan: isCyan,
        })
      }
    }

    const resize = () => {
      const DPR = Math.min(window.devicePixelRatio || 1, 2)
      W = window.innerWidth
      H = window.innerHeight
      canvas.width = Math.round(W * DPR)
      canvas.height = Math.round(H * DPR)
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0)
      build()
      if (!running) render(0)
    }

    function render(t: number) {
      ctx!.clearRect(0, 0, W, H)
      pointer.cx += (pointer.x - pointer.cx) * 0.045
      pointer.cy += (pointer.y - pointer.cy) * 0.045
      const offX = (pointer.cx - 0.5) * 34
      const offY = (pointer.cy - 0.5) * 26
      const time = t * 0.001

      const linkCount = Math.min(parts.length, 38)
      ctx!.lineWidth = 1
      for (let i = 0; i < linkCount; i++) {
        for (let j = i + 1; j < linkCount; j++) {
          const a = parts[i]
          const b = parts[j]
          const dx = a.x - b.x
          const dy = a.y - b.y
          const d2 = dx * dx + dy * dy
          if (d2 > 14400) continue
          const d = Math.sqrt(d2)
          ctx!.strokeStyle = `rgba(46,120,200,${((1 - d / 120) * 0.1).toFixed(3)})`
          ctx!.beginPath()
          ctx!.moveTo(a.x, a.y)
          ctx!.lineTo(b.x, b.y)
          ctx!.stroke()
        }
      }

      for (const p of parts) {
        p.x += p.vx + Math.sin(time * p.speed + p.phase) * 0.14
        p.y += p.vy
        if (p.y < -12) {
          p.y = H + 12
          p.x = rand(0, W)
        }
        if (p.x < -12) p.x = W + 12
        if (p.x > W + 12) p.x = -12
        const twinkle = 0.62 + Math.sin(time * p.speed * 1.6 + p.phase) * 0.38
        ctx!.globalAlpha = p.base * twinkle
        const px = p.x + offX * p.depth
        const py = p.y + offY * p.depth
        const rr = p.r * 4.2
        ctx!.drawImage(p.cyan ? spriteCyan : spriteWhite, px - rr, py - rr, rr * 2, rr * 2)
      }
      ctx!.globalAlpha = 1
    }

    function loop(t: number) {
      if (!running) return
      render(t)
      rafId = window.requestAnimationFrame(loop)
    }
    const start = () => {
      if (running || reduceMotion) return
      running = true
      rafId = window.requestAnimationFrame(loop)
    }
    const stop = () => {
      running = false
      if (rafId) {
        window.cancelAnimationFrame(rafId)
        rafId = null
      }
    }

    let rt: number | undefined
    const onResize = () => {
      window.clearTimeout(rt)
      rt = window.setTimeout(resize, 140)
    }
    const onPointerMove = (e: PointerEvent) => {
      pointer.x = e.clientX / Math.max(W, 1)
      pointer.y = e.clientY / Math.max(H, 1)
    }
    const onVisibility = () => {
      if (document.hidden) stop()
      else start()
    }

    window.addEventListener('resize', onResize, { passive: true })
    window.addEventListener('pointermove', onPointerMove, { passive: true })
    document.addEventListener('visibilitychange', onVisibility)
    resize()
    if (!reduceMotion) start()

    return () => {
      stop()
      window.clearTimeout(rt)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('pointermove', onPointerMove)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  /* ---------- 面板跟随光斑 ---------- */
  const onCardPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const card = cardRef.current
    if (!card) return
    const r = card.getBoundingClientRect()
    card.style.setProperty('--mx', `${((e.clientX - r.left) / r.width) * 100}%`)
    card.style.setProperty('--my', `${((e.clientY - r.top) / r.height) * 100}%`)
  }

  /* ---------- 登录提交 ---------- */
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (loading || leaving) return

    let ok = true
    if (!account.trim()) {
      setAccountHint({ text: '请填写账号，手机号或邮箱都可以', on: true })
      ok = false
    }
    if (password.length < 6) {
      setPasswordHint({ text: password ? '密码至少 6 位' : '请填写密码', on: true })
      ok = false
    }
    if (!ok) {
      setStatus({ text: '还差一步，检查一下标红的输入框', tone: 'warn' })
      return
    }

    setLoading(true)
    setStatus({ text: '正在验证账号' })
    try {
      const authUser: AuthUser = await apiLogin(account, password, role)
      setStatus({ text: '登录成功，正在进入工作台', tone: 'ok' })
      // 先播整页淡出，再把用户写入全局状态切换到主应用，衔接更丝滑
      setLeaving(true)
      window.setTimeout(() => signIn(authUser), 340)
    } catch (err) {
      setLoading(false)
      setStatus({ text: err instanceof Error ? err.message : '登录失败，请稍后再试', tone: 'warn' })
    }
  }

  /* ---------- 未登录修改密码 ---------- */
  const submitPassword = async () => {
    if (!pwdAccount.trim() || !pwdOld || !pwdNew) {
      setPwdStatus({ text: '请填写账号、原密码和新密码', tone: 'warn' })
      return
    }
    if (pwdNew.length < 6) {
      setPwdStatus({ text: '新密码至少 6 位', tone: 'warn' })
      return
    }
    if (pwdNew !== pwdConfirm) {
      setPwdStatus({ text: '两次输入的新密码不一致', tone: 'warn' })
      return
    }
    setPwdBusy(true)
    try {
      await changePassword(pwdAccount.trim(), pwdOld, pwdNew, role)
      setPwdStatus({ text: '密码已修改，请使用新密码登录', tone: 'ok' })
      setPwdOld('')
      setPwdNew('')
      setPwdConfirm('')
      setPassword('')
    } catch (err) {
      setPwdStatus({ text: err instanceof Error ? err.message : '修改密码失败', tone: 'warn' })
    } finally {
      setPwdBusy(false)
    }
  }

  return (
    <div className="stage" data-leaving={leaving ? 'true' : undefined}>
      {/* 背景与质感层 */}
      <div className="login-bg" aria-hidden="true" />
      <canvas ref={dustRef} className="login-dust" aria-hidden="true" />
      <div className="login-grain" aria-hidden="true" />
      <div className="login-vignette" aria-hidden="true" />

      {/* 品牌：去掉左侧 logo，整体左移 */}
      <header className="login-brand">
        <span>
          <span className="login-brand__name">MathCraft</span>
          <span className="login-brand__sub">智能出题平台</span>
        </span>
      </header>

      {/* 主体 */}
      <div className="login-layout">
        <section className="login-intro">
          <div className="login-intro__rule" aria-hidden="true" />
          <h2>
            从知识库
            <br />
            到成套题目
          </h2>
          <p>上传课件与教材，按章节、难度和题型生成题干与解析，再一键成卷发布。</p>
        </section>

        <section className="login-panel" aria-labelledby="login-title">
          <div className="login-halo" aria-hidden="true" />

          <div className="login-card" ref={cardRef} onPointerMove={onCardPointerMove}>
            <div className="login-card__head">
              <h1 id="login-title">欢迎回来</h1>
              <p className="login-lede">{ROLE_COPY[role].lede}</p>
            </div>

            <form className="login-form" noValidate onSubmit={(e) => void submit(e)}>
              <fieldset className="login-seg">
                <legend>选择身份</legend>
                <input
                  type="radio"
                  id="role-student"
                  name="role"
                  value="student"
                  checked={role === 'student'}
                  onChange={() => {
                    setRole('student')
                    resetField(setAccountHint)
                    resetField(setPasswordHint)
                    setStatus(null)
                  }}
                />
                <label htmlFor="role-student" className={role === 'student' ? 'is-active' : ''}>
                  学生
                </label>
                <input
                  type="radio"
                  id="role-teacher"
                  name="role"
                  value="teacher"
                  checked={role === 'teacher'}
                  onChange={() => {
                    setRole('teacher')
                    resetField(setAccountHint)
                    resetField(setPasswordHint)
                    setStatus(null)
                  }}
                />
                <label htmlFor="role-teacher" className={role === 'teacher' ? 'is-active' : ''}>
                  老师
                </label>
                <span className={`login-seg__thumb ${role === 'teacher' ? 'is-right' : ''}`} aria-hidden="true" />
              </fieldset>

              <div className="login-field">
                <label className="login-field__label" htmlFor="account">
                  账号
                </label>
                <div className="login-field__box" data-invalid={accountHint.on ? 'true' : undefined}>
                  <svg
                    className="login-field__icon"
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <circle cx="12" cy="8" r="3.6" />
                    <path d="M4.8 19.6a7.2 7.2 0 0 1 14.4 0" />
                  </svg>
                  <input
                    id="account"
                    name="account"
                    type="text"
                    inputMode="email"
                    autoComplete="username"
                    value={account}
                    onChange={(e) => {
                      setAccount(e.target.value)
                      resetField(setAccountHint)
                      setStatus(null)
                    }}
                    placeholder={ROLE_COPY[role].account}
                    enterKeyHint="next"
                  />
                </div>
                <p className="login-hint" aria-live="polite" data-on={accountHint.on ? 'true' : undefined}>
                  {accountHint.text}
                </p>
              </div>

              <div className="login-field">
                <label className="login-field__label" htmlFor="password">
                  密码
                </label>
                <div className="login-field__box" data-invalid={passwordHint.on ? 'true' : undefined}>
                  <svg
                    className="login-field__icon"
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <rect x="4.5" y="10.4" width="15" height="9.6" rx="2.6" />
                    <path d="M8.2 10.4V7.8a3.8 3.8 0 0 1 7.6 0v2.6" />
                  </svg>
                  <input
                    id="password"
                    name="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value)
                      resetField(setPasswordHint)
                      setStatus(null)
                    }}
                    placeholder="请输入密码"
                    enterKeyHint="go"
                  />
                  <button
                    className="login-reveal"
                    type="button"
                    aria-label={showPassword ? '隐藏密码' : '显示密码'}
                    aria-pressed={showPassword}
                    onClick={() => setShowPassword((v) => !v)}
                  >
                    {showPassword ? (
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M4 4.6 20 20" />
                        <path d="M9.7 6a10.8 10.8 0 0 1 2.3-.4c6 0 9.6 6.4 9.6 6.4a17.6 17.6 0 0 1-3.2 3.9" />
                        <path d="M6.5 7.7A16.4 16.4 0 0 0 2.4 12S6 18.4 12 18.4a10.4 10.4 0 0 0 3.4-.5" />
                        <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
                      </svg>
                    ) : (
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M2.4 12S6 5.6 12 5.6 21.6 12 21.6 12 18 18.4 12 18.4 2.4 12 2.4 12Z" />
                        <circle cx="12" cy="12" r="2.9" />
                      </svg>
                    )}
                  </button>
                </div>
                <p className="login-hint" aria-live="polite" data-on={passwordHint.on ? 'true' : undefined}>
                  {passwordHint.text}
                </p>
              </div>

              <div className="login-assist">
                <button
                  type="button"
                  className="login-link"
                  onClick={() => {
                    setPwdAccount(account)
                    setPwdStatus(null)
                    setPwdOpen(true)
                  }}
                >
                  修改密码
                </button>
                <button
                  type="button"
                  className="login-link"
                  onClick={() => setStatus({ text: '功能暂未开发', tone: 'warn' })}
                >
                  忘记密码？
                </button>
              </div>

              <button className="login-cta" type="submit" disabled={loading || leaving} data-loading={loading ? 'true' : undefined}>
                <span className="login-cta__spin" aria-hidden="true" />
                <span>{ROLE_COPY[role].cta}</span>
              </button>

              <p className="login-status" role="status" aria-live="polite" data-tone={status?.tone}>
                {status?.text}
              </p>
            </form>
          </div>
        </section>
      </div>

      <footer className="login-legal">
        <span>© 2026 MathCraft</span>
        <span className="login-legal__tag">
          <span className="login-legal__dot" aria-hidden="true" />
          v0.1.0
        </span>
      </footer>

      {pwdOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={() => setPwdOpen(false)}>
          <div className="w-[420px] overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <h3 className="text-base font-bold text-ink">修改密码</h3>
              <button type="button" onClick={() => setPwdOpen(false)} className="rounded p-1 text-ink-3 hover:bg-page">
                ×
              </button>
            </div>
            <div className="space-y-3 px-5 py-4">
              <p className="text-xs text-ink-3">身份：{role === 'teacher' ? '老师' : '学生'}</p>
              <input
                type="text"
                value={pwdAccount}
                onChange={(e) => setPwdAccount(e.target.value)}
                placeholder="账号"
                className="block w-full rounded-lg border border-line px-3 py-2 text-sm text-ink outline-none focus:border-primary"
              />
              <input
                type="password"
                value={pwdOld}
                onChange={(e) => setPwdOld(e.target.value)}
                placeholder="原密码"
                className="block w-full rounded-lg border border-line px-3 py-2 text-sm text-ink outline-none focus:border-primary"
              />
              <input
                type="password"
                value={pwdNew}
                onChange={(e) => setPwdNew(e.target.value)}
                placeholder="新密码（至少 6 位）"
                className="block w-full rounded-lg border border-line px-3 py-2 text-sm text-ink outline-none focus:border-primary"
              />
              <input
                type="password"
                value={pwdConfirm}
                onChange={(e) => setPwdConfirm(e.target.value)}
                placeholder="确认新密码"
                className="block w-full rounded-lg border border-line px-3 py-2 text-sm text-ink outline-none focus:border-primary"
              />
              {pwdStatus && (
                <p className={`text-xs ${pwdStatus.tone === 'ok' ? 'text-emerald-600' : 'text-amber-600'}`}>{pwdStatus.text}</p>
              )}
            </div>
            <div className="flex justify-end gap-2.5 border-t border-line px-5 py-3.5">
              <button
                type="button"
                onClick={() => setPwdOpen(false)}
                className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 hover:bg-page"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void submitPassword()}
                disabled={pwdBusy}
                className="rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {pwdBusy ? '提交中…' : '确认修改'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
