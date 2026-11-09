/** 管理员开通账号，默认密码登录；绑定邮箱后可使用验证码登录。 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, developmentAccount, getAuthConfig, loginAccount, loginEmail, resetPassword, validateNewPassword } from '../../api/auth'
import type { AuthRole } from '../../api/auth'
import { useAuth } from '../../store/AuthContext'
import { EmailCodeFields } from './EmailCodeFields'
import { Turnstile } from './Turnstile'
import '../../styles/login.css'

type Mode = 'password' | 'email' | 'reset'
const titles: Record<Mode, string> = { password: '账号登录', email: '账号登录', reset: '找回密码' }

export default function LoginPage() {
  const { signIn, restoreError, logoutError, authNotice, restore, logout } = useAuth()
  const [mode, setMode] = useState<Mode>('password')
  const [email, setEmail] = useState('')
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [challengeId, setChallengeId] = useState('')
  const [code, setCode] = useState('')
  const [token, setToken] = useState('')
  const [turnstileRequired, setTurnstileRequired] = useState(true)
  const [epoch, setEpoch] = useState(0)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [retryAt, setRetryAt] = useState(0)
  const [now, setNow] = useState(Date.now)
  const [devEnabled, setDevEnabled] = useState(false)
  const [adminContact, setAdminContact] = useState('请联系本校或平台管理员')
  const passwordMode = mode === 'password'

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

  function switchMode(next: Mode) {
    setMode(next)
    setPassword('')
    setConfirm('')
    setCode('')
    setChallengeId('')
    setStatus('')
    setToken('')
    setEpoch(value => value + 1)
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || now < retryAt) return
    if (mode === 'reset') {
      const error = validateNewPassword(password)
      if (error || password !== confirm) {
        setStatus(error ?? '两次密码输入不一致')
        return
      }
    }
    if (!passwordMode && (!challengeId || !/^\d{6}$/.test(code))) {
      setStatus('请发送并填写 6 位邮箱验证码')
      return
    }
    if (passwordMode && turnstileRequired && !token) { setStatus('请先完成人机验证'); return }
    setBusy(true)
    setStatus('')
    try {
      const proof = { email: email.trim(), challenge_id: challengeId, code }
      if (mode === 'reset') {
        await resetPassword({ ...proof, new_password: password, confirm_password: confirm })
        switchMode('password')
        setStatus('密码已重置，所有设备已下线，请使用新密码登录')
        return
      }
      const user = passwordMode
        ? await loginAccount(account.trim(), password, token)
        : await loginEmail(proof)
      setPassword('')
      setConfirm('')
      signIn(user)
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
    setBusy(true)
    setStatus('')
    try {
      const sample = await developmentAccount(role)
      switchMode('password')
      setAccount(sample.account)
      setPassword(sample.password)
      setStatus(turnstileRequired ? '已填充开发账号，请完成人机验证后手动登录' : '已填充开发账号，请手动登录')
    } catch (reason: unknown) {
      setStatus(reason instanceof Error ? reason.message : '开发账号不可用')
    } finally { setBusy(false) }
  }

  return <div className="stage auth-stage">
    <div className="login-bg" aria-hidden="true" /><div className="login-grain" aria-hidden="true" /><div className="login-vignette" aria-hidden="true" />
    <header className="login-brand"><span><span className="login-brand__name">MathCraft</span><span className="login-brand__sub">智能出题平台</span></span></header>
    <div className="login-layout">
      <section className="login-intro"><div className="login-intro__rule" aria-hidden="true" /><h2>从知识库<br />到成套题目</h2><p>上传课件与教材，按章节、难度和题型生成题干与解析，再一键成卷发布。</p></section>
      <section className="login-panel" aria-labelledby="login-title"><div className="login-halo" aria-hidden="true" /><div className="login-card">
        <div className="login-card__head"><h1 id="login-title">{titles[mode]}</h1><p className="login-lede">{mode === 'reset' ? '验证绑定邮箱后重置密码' : '使用管理员开通的账号进入工作空间'}</p></div>
        {authNotice && <p role="status" className="auth-notice">{authNotice}</p>}
        {logoutError && <div role="alert" className="auth-notice">{logoutError}<button type="button" disabled={busy} onClick={() => void retryLogout()}>重试退出</button></div>}
        {restoreError && <div role="alert" className="auth-notice">{restoreError}<button type="button" disabled={busy} onClick={restore}>重试恢复</button></div>}
        <nav className="auth-modes" aria-label="认证方式">
          {(['password', 'email'] as const).map(item => <button key={item} type="button" aria-pressed={mode === item} disabled={busy} onClick={() => switchMode(item)}>{item === 'password' ? '密码登录' : '邮箱登录'}</button>)}
        </nav>
        <form className="login-form auth-form" onSubmit={event => void submit(event)}>
          <fieldset className="auth-fields" disabled={busy}>
            {passwordMode ? <>
              <label className="auth-field"><span>登录账号</span><input required autoComplete="username" value={account} maxLength={64} onChange={event => setAccount(event.target.value)} /></label>
              <p className="auth-help">请输入管理员分配的登录账号</p>
            </> : <>
              <label className="auth-field"><span>邮箱</span><input type="email" autoComplete="email" required maxLength={128} value={email} onChange={event => { setEmail(event.target.value); setChallengeId(''); setCode('') }} /></label>
              <p className="auth-help">请使用个人设置中已绑定并验证的邮箱</p>
            </>}
            {mode !== 'email' && <label className="auth-field"><span>{mode === 'reset' ? '新密码' : '密码'}</span><input type="password" autoComplete={passwordMode ? 'current-password' : 'new-password'} required value={password} onChange={event => setPassword(event.target.value)} /></label>}
            {mode === 'reset' && <>
              <label className="auth-field"><span>确认新密码</span><input type="password" autoComplete="new-password" required value={confirm} onChange={event => setConfirm(event.target.value)} /></label>
              <p className="auth-help">8–64 字符，UTF-8 不超过 72 字节</p>
            </>}
            {!passwordMode && <EmailCodeFields key={mode + ':' + email} email={email} purpose={mode === 'reset' ? 'reset_password' : 'login'} onProof={(id, value) => { setChallengeId(id); setCode(value) }} />}
            {passwordMode && <Turnstile key={epoch} action="password_login" onToken={setToken} onRequired={setTurnstileRequired} />}
          </fieldset>
          {status && <p className="auth-notice" role="status">{status}</p>}
          <button className="auth-primary" type="submit" disabled={busy || now < retryAt || (passwordMode && turnstileRequired && !token)}>{busy ? '处理中…' : now < retryAt ? Math.ceil((retryAt - now) / 1000) + ' 秒后重试' : mode === 'reset' ? '重置密码' : '登录并进入工作台'}</button>
          <button className="auth-link" type="button" disabled={busy} onClick={() => switchMode(mode === 'reset' ? 'password' : 'reset')}>{mode === 'reset' ? '返回密码登录' : '忘记密码？'}</button>
        </form>
        <p className="auth-help">账号由管理员创建；未绑定邮箱或无法找回密码：{adminContact}</p>
        {import.meta.env.DEV && devEnabled && window.location.hostname === '127.0.0.1' && <div className="auth-dev">{(['student', 'teacher'] as const).map(item => <button key={item} type="button" disabled={busy} onClick={() => void fillDevelopment(item)}>填充{item === 'student' ? '学生' : '教师'}开发账号</button>)}</div>}
      </div></section>
    </div>
  </div>
}
