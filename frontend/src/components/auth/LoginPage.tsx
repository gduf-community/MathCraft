/** 沿用 MathCraft 背景、品牌、玻璃面板和蓝色控件的自助认证入口。 */
import { useEffect, useState } from 'react'
import { ApiError, developmentAccount, getAuthConfig, loginEmail, loginPassword, register, resetPassword, validateNewPassword } from '../../api/auth'
import type { AuthRole } from '../../api/auth'
import { useAuth } from '../../store/AuthContext'
import { EmailCodeFields } from './EmailCodeFields'
import { Turnstile } from './Turnstile'
import '../../styles/login.css'
type Mode = 'email' | 'password' | 'register' | 'reset'
const titles: Record<Mode, string> = { email: '欢迎回来', password: '欢迎回来', register: '创建你的账号', reset: '找回密码' }
export default function LoginPage() {
  const { signIn, restoreError, logoutError, restore, logout } = useAuth()
  const [mode, setMode] = useState<Mode>('email')
  const [role, setRole] = useState<AuthRole>('student')
  const [email, setEmail] = useState('')
  const [userNo, setUserNo] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [challengeId, setChallengeId] = useState('')
  const [code, setCode] = useState('')
  const [token, setToken] = useState('')
  const [epoch, setEpoch] = useState(0)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [retryAt, setRetryAt] = useState(0)
  const [now, setNow] = useState(Date.now)
  const [devEnabled, setDevEnabled] = useState(false)
  useEffect(() => {
    if (import.meta.env.DEV && window.location.hostname === '127.0.0.1') {
      void getAuthConfig().then(config => setDevEnabled(config.development_accounts_enabled === true)).catch(() => setDevEnabled(false))
    }
  }, [])
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(id) }, [])
  function switchMode(next: Mode) {
    setMode(next); setPassword(''); setConfirm(''); setCode(''); setChallengeId(''); setStatus(''); setToken(''); setEpoch(n => n + 1)
  }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || now < retryAt) return
    if (mode === 'register' || mode === 'reset') {
      const error = validateNewPassword(password)
      if (error || password !== confirm) { setStatus(error ?? '两次密码输入不一致'); return }
    }
    if (mode !== 'password' && (!challengeId || !/^\d{6}$/.test(code))) { setStatus('请发送并填写 6 位邮箱验证码'); return }
    if (mode === 'password' && !token) { setStatus('请先完成人机验证'); return }
    setBusy(true); setStatus('')
    try {
      const proof = { email: email.trim(), challenge_id: challengeId, code }
      if (mode === 'reset') {
        await resetPassword({ ...proof, new_password: password, confirm_password: confirm }); switchMode('email'); setStatus('密码已重置，所有设备已下线，请重新登录'); return
      }
      const user = mode === 'register'
        ? await register({ ...proof, password, confirm_password: confirm, display_name: displayName.trim(), role, user_no: userNo.trim() || null })
        : mode === 'email' ? await loginEmail({ ...proof, role }) : await loginPassword(userNo.trim(), password, role, token)
      setPassword(''); setConfirm(''); signIn(user)
    } catch (reason) {
      if (reason instanceof ApiError && reason.retryAfter) setRetryAt(Date.now() + reason.retryAfter * 1000)
      setStatus(reason instanceof Error ? reason.message : '认证失败，请稍后重试')
      // 错码、网络错误均不清空两个密码；只在成功或离开流程时清理。
    } finally { setBusy(false); setToken(''); setEpoch(n => n + 1) }
  }
  async function retryLogout() {
    setBusy(true)
    try { await logout() }
    catch (reason: unknown) { setStatus(reason instanceof Error ? reason.message : '服务端退出尚未确认') }
    finally { setBusy(false) }
  }
  async function fillDevelopment(nextRole: AuthRole) {
    setBusy(true); setStatus('')
    try {
      const account = await developmentAccount(nextRole)
      switchMode('password'); setRole(nextRole); setUserNo(account.user_no); setPassword(account.password); setStatus('已填充开发账号，请完成人机验证后手动登录')
    } catch (reason) { setStatus(reason instanceof Error ? reason.message : '开发账号不可用') } finally { setBusy(false) }
  }
  return <div className="stage auth-stage">
    <div className="login-bg" aria-hidden="true" /><div className="login-grain" aria-hidden="true" /><div className="login-vignette" aria-hidden="true" />
    <header className="login-brand"><span><span className="login-brand__name">MathCraft</span><span className="login-brand__sub">智能出题平台</span></span></header>
    <div className="login-layout"><section className="login-intro"><div className="login-intro__rule" aria-hidden="true" /><h2>从知识库<br />到成套题目</h2><p>上传课件与教材，按章节、难度和题型生成题干与解析，再一键成卷发布。</p></section>
      <section className="login-panel" aria-labelledby="login-title"><div className="login-halo" aria-hidden="true" /><div className="login-card">
        <div className="login-card__head"><h1 id="login-title">{titles[mode]}</h1><p className="login-lede">{mode === 'reset' ? '使用绑定邮箱验证身份，重置后需重新登录' : '教师与学生的独立工作空间'}</p></div>
        {logoutError && <div role="alert" className="auth-notice">{logoutError}<button type="button" disabled={busy} onClick={() => void retryLogout()}>重试退出</button></div>}
        {restoreError && <div role="alert" className="auth-notice">{restoreError}<button type="button" disabled={busy} onClick={restore}>重试恢复</button></div>}
        <nav className="auth-modes" aria-label="认证方式">{(['email', 'password', 'register'] as const).map(item => <button key={item} type="button" aria-pressed={mode === item} disabled={busy} onClick={() => switchMode(item)}>{item === 'email' ? '邮箱码登录' : item === 'password' ? '学工号登录' : '注册账号'}</button>)}</nav>
        <form className="login-form auth-form" onSubmit={event => void submit(event)}>
          <fieldset className="auth-role" disabled={busy}><legend>选择身份</legend>{(['student', 'teacher'] as const).map(item => <label key={item}><input type="radio" name="role" checked={role === item} onChange={() => { setRole(item); setStatus('') }} />{item === 'student' ? '学生' : '教师'}</label>)}</fieldset>
          <fieldset className="auth-fields" disabled={busy}>
          {mode !== 'password' && <label className="auth-field"><span>邮箱</span><input type="email" autoComplete="email" required maxLength={128} value={email} onChange={e => { setEmail(e.target.value); setChallengeId(''); setCode('') }} /></label>}
          {mode === 'register' && <label className="auth-field"><span>显示名称</span><input required maxLength={64} value={displayName} onChange={e => setDisplayName(e.target.value)} /></label>}
          {(mode === 'register' || mode === 'password') && <label className="auth-field"><span>{mode === 'register' ? '学工号（可选）' : '学工号'}</span><input required={mode === 'password'} autoComplete="username" value={userNo} maxLength={32} onChange={e => setUserNo(e.target.value)} /></label>}
          {mode !== 'email' && <label className="auth-field"><span>{mode === 'reset' ? '新密码' : '密码'}</span><input type="password" autoComplete={mode === 'password' ? 'current-password' : 'new-password'} required value={password} onChange={e => setPassword(e.target.value)} /></label>}
          {(mode === 'register' || mode === 'reset') && <><label className="auth-field"><span>{mode === 'reset' ? '确认新密码' : '确认密码'}</span><input type="password" autoComplete="new-password" required value={confirm} onChange={e => setConfirm(e.target.value)} /></label><p className="auth-help">8–64 字符，UTF-8 不超过 72 字节</p></>}
          {mode !== 'password' && <EmailCodeFields key={mode + ':' + email} email={email} purpose={mode === 'reset' ? 'reset_password' : mode === 'register' ? 'register' : 'login'} onProof={(id, value) => { setChallengeId(id); setCode(value) }} />}
          {mode === 'password' && <Turnstile key={epoch} action="password_login" onToken={setToken} />}
          </fieldset>
          {status && <p className="auth-notice" role="status">{status}</p>}
          <button className="auth-primary" type="submit" disabled={busy || now < retryAt || (mode === 'password' && !token)}>{busy ? '处理中…' : now < retryAt ? Math.ceil((retryAt - now) / 1000) + ' 秒后重试' : mode === 'register' ? '注册并进入工作台' : mode === 'reset' ? '重置密码' : '登录并进入工作台'}</button>
          <button className="auth-link" type="button" disabled={busy} onClick={() => switchMode(mode === 'reset' ? 'email' : 'reset')}>{mode === 'reset' ? '返回登录' : '忘记密码？'}</button>
        </form>
        {import.meta.env.DEV && devEnabled && window.location.hostname === '127.0.0.1' && <div className="auth-dev">{(['student', 'teacher'] as const).map(item => <button key={item} type="button" disabled={busy} onClick={() => void fillDevelopment(item)}>填充{item === 'student' ? '学生' : '教师'}开发账号</button>)}</div>}
      </div></section>
    </div>
  </div>
}
