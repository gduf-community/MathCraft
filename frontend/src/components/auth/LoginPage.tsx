/** 管理员开通账号，默认密码登录；绑定邮箱后可使用验证码登录。 */
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowRight, Eye, EyeOff, LockKeyhole, UserRound } from 'lucide-react'
import { ApiError, developmentAccount, getAuthConfig, loginAccount } from '../../api/auth'
import type { AuthRole, AuthUser } from '../../api/auth'
import { useAuth } from '../../store/AuthContext'
import { AuthDialog } from './AuthDialog'
import { LoginEmailBindingDialog } from './LoginEmailBindingDialog'
import { Turnstile } from './Turnstile'
import '../../styles/login.css'

export default function LoginPage() {
  const stageRef = useRef<HTMLDivElement>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const dustRef = useRef<HTMLCanvasElement>(null)
  const emailLoginRef = useRef<HTMLButtonElement>(null)
  const [role, setRole] = useState<Exclude<AuthRole, 'admin'>>('student')
  const [showPassword, setShowPassword] = useState(false)
  const { signIn, restoreError, logoutError, authNotice, restore, logout } = useAuth()
  const [dialog, setDialog] = useState<'email' | 'reset' | 'bind' | null>(null)
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [token, setToken] = useState('')
  const [turnstileRequired, setTurnstileRequired] = useState(true)
  const [epoch, setEpoch] = useState(0)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [retryAt, setRetryAt] = useState(0)
  const [now, setNow] = useState(Date.now)
  const [devEnabled, setDevEnabled] = useState(false)
  const [adminContact, setAdminContact] = useState('请联系本校或平台管理员')

  useEffect(() => {
    const viewport = window.visualViewport
    const stage = stageRef.current
    if (!viewport || !stage) return
    // 软键盘和页面放大可能只改变视觉视口，不改变 100dvh。
    function syncViewport() {
      if (!viewport || !stage) return
      stage.style.setProperty('--login-viewport-height', `${viewport.height}px`)
      stage.style.setProperty('--login-viewport-width', `${viewport.width}px`)
      stage.style.setProperty('--login-viewport-top', `${viewport.offsetTop}px`)
      stage.style.setProperty('--login-viewport-left', `${viewport.offsetLeft}px`)
    }
    syncViewport()
    viewport.addEventListener('resize', syncViewport)
    viewport.addEventListener('scroll', syncViewport)
    return () => {
      viewport.removeEventListener('resize', syncViewport)
      viewport.removeEventListener('scroll', syncViewport)
    }
  }, [])

  useEffect(() => {
    let active = true
    async function loadConfig() {
      try {
        const config = await getAuthConfig()
        if (!active) return
        setAdminContact(config.admin_contact || '请联系本校或平台管理员')
        setDevEnabled(import.meta.env.DEV && window.location.hostname === '127.0.0.1' && config.development_accounts_enabled === true)
      } catch (error: unknown) {
        if (active) setStatus(error instanceof Error ? error.message : '认证配置加载失败')
      }
    }
    void loadConfig()
    return () => { active = false }
  }, [])
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
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

  function clearPassword() {
    setShowPassword(false)
    setPassword('')
    setToken('')
    setEpoch(value => value + 1)
  }

  function openDialog(next: 'email' | 'reset' | 'bind') {
    if (busy) return
    clearPassword()
    setStatus('')
    setDialog(next)
  }

  function closeDialog() {
    setDialog(null)
    clearPassword()
    if (dialog === 'bind') window.requestAnimationFrame(() => emailLoginRef.current?.focus())
  }

  async function completeLogin(user: AuthUser) {
    setPassword('')
    if (user.role !== 'admin' && user.role !== role) {
      await logout()
      throw new Error(`该账号为${user.role === 'teacher' ? '教师' : '学生'}账号，请选择对应身份后重新登录`)
    }
    signIn(user)
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || dialog !== null || now < retryAt) return
    if (turnstileRequired && !token) { setStatus('请先完成人机验证'); return }
    setBusy(true)
    setStatus('')
    try {
      const user = await loginAccount(account.trim(), password, token)
      await completeLogin(user)
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.retryAfter) setRetryAt(Date.now() + reason.retryAfter * 1000)
      setStatus(reason instanceof Error ? reason.message : '认证失败，请稍后重试')
    } finally {
      setBusy(false)
      setToken('')
      setEpoch(value => value + 1)
    }
  }

  async function retryLogout() {
    setBusy(true)
    try { await logout() }
    catch (reason: unknown) { setStatus(reason instanceof Error ? reason.message : '服务端退出尚未确认') }
    finally { setBusy(false) }
  }

  async function fillDevelopment(role: Exclude<AuthRole, 'admin'>) {
    setRole(role)
    setBusy(true)
    setStatus('')
    try {
      const sample = await developmentAccount(role)
      clearPassword()
      setAccount(sample.account)
      setPassword(sample.password)
      setStatus(turnstileRequired ? '已填充开发账号，请完成人机验证后手动登录' : '已填充开发账号，请手动登录')
    } catch (reason: unknown) {
      setStatus(reason instanceof Error ? reason.message : '开发账号不可用')
    } finally { setBusy(false) }
  }

  return <div ref={stageRef} className="stage auth-stage">
    <div className="login-decoration" aria-hidden="true"><div className="login-bg" /><canvas ref={dustRef} className="login-dust" /><div className="login-grain" /><div className="login-vignette" /></div>
    <header className="login-brand"><span><span className="login-brand__name">MathCraft</span><span className="login-brand__sub">智能出题平台</span></span></header>
    <div className="login-layout">
      <section className="login-intro" aria-labelledby="login-intro-title">
        <div className="login-intro__rule" aria-hidden="true" />
        <h2 id="login-intro-title">从知识库<br />到成套题目</h2>
        <p>上传课件与教材，按章节、难度和题型生成题干与解析，再一键成卷发布。</p>
      </section>
      <section className="login-panel" aria-labelledby="login-title"><div className="login-halo" aria-hidden="true" /><div className="login-card" ref={cardRef} onPointerMove={onCardPointerMove}><div className="login-card__body" tabIndex={0} role="region" aria-labelledby="login-title">
        <div className="login-card__head"><h1 id="login-title">欢迎回来</h1><p className="login-lede">{role === 'teacher' ? '登录后继续出题、组卷与发布' : '登录后继续练习与错题回顾'}</p></div>
        {authNotice && <p role="status" className="auth-notice">{authNotice}</p>}
        {logoutError && <div role="alert" className="auth-notice">{logoutError}<button type="button" disabled={busy} onClick={() => void retryLogout()}>重试退出</button></div>}
        {restoreError && <div role="alert" className="auth-notice">{restoreError}<button type="button" disabled={busy} onClick={restore}>重试恢复</button></div>}
        <fieldset className="login-seg" disabled={busy}>
          <legend>选择身份</legend>
          {(['student', 'teacher'] as const).map(item => <span key={item} className="login-role-option">
            <input type="radio" id={`role-${item}`} name="role" value={item} checked={role === item} onChange={() => { setRole(item); setStatus('') }} />
            <label htmlFor={`role-${item}`} className={role === item ? 'is-active' : ''}>{item === 'student' ? '学生' : '教师'}</label>
          </span>)}
          <span className={`login-seg__thumb${role === 'teacher' ? ' is-right' : ''}`} aria-hidden="true" />
        </fieldset>
        <form className="login-form auth-form" onSubmit={event => void submit(event)}>
          <fieldset className="auth-fields" disabled={busy}>
            <label className="auth-field"><span>登录账号</span><span className="login-field__box"><UserRound size={18} className="login-field__icon" aria-hidden="true" /><input aria-label="登录账号" placeholder="请输入管理员分配的登录账号" required autoComplete="username" value={account} maxLength={64} onChange={event => setAccount(event.target.value)} /></span></label>
            <label className="auth-field"><span>密码</span><span className="login-field__box"><LockKeyhole size={18} className="login-field__icon" aria-hidden="true" /><input aria-label="密码" placeholder="请输入密码" type={showPassword ? 'text' : 'password'} autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} /><button className="login-reveal" type="button" aria-label={showPassword ? '隐藏密码' : '显示密码'} aria-pressed={showPassword} onClick={() => setShowPassword(value => !value)}>{showPassword ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}</button></span></label>
            <Turnstile key={epoch} action="password_login" onToken={setToken} onRequired={setTurnstileRequired} />
          </fieldset>
          <div className="login-assist">
            <button ref={emailLoginRef} className="login-link auth-link" type="button" disabled={busy} onClick={() => openDialog('email')}>邮箱登录</button>
            <button className="login-link auth-link" type="button" disabled={busy} onClick={() => openDialog('reset')}>忘记密码？</button>
          </div>
          {status && <p className="auth-notice" role="status">{status}</p>}
          <button className="login-cta" data-loading={busy} type="submit" disabled={busy || now < retryAt || (turnstileRequired && !token)}><span className="login-cta__spin" aria-hidden="true" /><span>{busy ? '处理中…' : now < retryAt ? Math.ceil((retryAt - now) / 1000) + ' 秒后重试' : role === 'teacher' ? '进入教师工作台' : '进入学习空间'}</span><ArrowRight size={18} aria-hidden="true" /></button>
        </form>
        {import.meta.env.DEV && devEnabled && window.location.hostname === '127.0.0.1' && <div className="auth-dev">{(['student', 'teacher'] as const).map(item => <button key={item} type="button" disabled={busy} onClick={() => void fillDevelopment(item)}>填充{item === 'student' ? '学生' : '教师'}开发账号</button>)}</div>}
      </div></div></section>
    </div>
    <footer className="login-legal"><span>© 2026 MathCraft</span><span className="login-legal__tag"><span className="login-legal__dot" aria-hidden="true" />v0.1.0</span></footer>
    {dialog === 'bind' && <LoginEmailBindingDialog
      role={role}
      initialAccount={account}
      now={now}
      retryAt={retryAt}
      onRateLimit={seconds => setRetryAt(Date.now() + seconds * 1000)}
      onClose={closeDialog}
      onBack={() => setDialog('email')}
      onBound={() => {
        closeDialog()
        setStatus('邮箱已绑定，所有设备已退出，请重新登录')
      }}
    />}
    {(dialog === 'email' || dialog === 'reset') && <AuthDialog
      kind={dialog}
      adminContact={adminContact}
      now={now}
      retryAt={retryAt}
      onRateLimit={seconds => setRetryAt(Date.now() + seconds * 1000)}
      onAuthenticated={completeLogin}
      onClose={closeDialog}
      onBindEmail={() => setDialog('bind')}
      onReset={() => {
        closeDialog()
        setStatus('密码已重置，所有设备已下线，请使用新密码登录')
      }}
    />}
  </div>
}
