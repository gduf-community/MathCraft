import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, bindEmail, loginAccount } from '../../api/auth'
import type { AuthRole } from '../../api/auth'
import { getSessionGeneration, onSessionCleared } from '../../api/session'
import { useAuth } from '../../store/AuthContext'
import { ConfigurationDialog } from '../ui/ConfigurationDialog'
import { EmailCodeFields } from './EmailCodeFields'
import { Turnstile } from './Turnstile'

interface LoginEmailBindingDialogProps {
  role: Exclude<AuthRole, 'admin'>
  initialAccount: string
  now: number
  retryAt: number
  onRateLimit: (seconds: number) => void
  onClose: () => void
  onBack: () => void
  onBound: () => void
}

/** 登录页只借用临时会话绑定邮箱，不向 AuthContext 安装用户身份。 */
export function LoginEmailBindingDialog({
  role, initialAccount, now, retryAt, onRateLimit, onClose, onBack, onBound,
}: LoginEmailBindingDialogProps) {
  const { logout, logoutError } = useAuth()
  const [step, setStep] = useState<'account' | 'email' | 'existing' | 'ended' | 'cleanup'>('account')
  const [account, setAccount] = useState(initialAccount)
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [challengeId, setChallengeId] = useState('')
  const [code, setCode] = useState('')
  const [token, setToken] = useState('')
  const [turnstileRequired, setTurnstileRequired] = useState(true)
  const [epoch, setEpoch] = useState(0)
  const [busy, setBusy] = useState(false)
  const [sendingCode, setSendingCode] = useState(false)
  const [status, setStatus] = useState('')
  const temporarySession = useRef<number | null>(null)
  const needsLogout = useRef(false)
  const lock = useRef(false)
  const returnTo = useRef<'password' | 'email'>('password')
  const mounted = useRef(true)
  const remaining = Math.max(0, Math.ceil((retryAt - now) / 1000))
  const requestBusy = busy || sendingCode

  useEffect(() => {
    mounted.current = true
    const unsubscribe = onSessionCleared(() => {
      if (temporarySession.current === null) return
      temporarySession.current = null
      needsLogout.current = false
      setPassword('')
      setChallengeId('')
      setCode('')
      setStep('ended')
      setStatus('临时会话已结束，请关闭弹窗后重新验证账号')
    })
    // 页面离开也先同步清掉本地会话及自动恢复意图；服务端撤销沿用现有接口。
    const revokeOnLeave = () => {
      if (temporarySession.current === null
        || temporarySession.current !== getSessionGeneration()) return
      temporarySession.current = null
      needsLogout.current = true
      if (mounted.current) {
        setPassword('')
        setChallengeId('')
        setCode('')
        setStep('ended')
        setStatus('临时会话已结束，请关闭弹窗后重新验证账号')
      }
      void logout().catch(() => {
        // logout 已保留仅用于撤销的凭据与 logoutError，禁止转为登录态。
        if (mounted.current) setStatus('临时会话退出尚未确认，请重试退出')
      })
    }
    window.addEventListener('pagehide', revokeOnLeave)
    return () => {
      mounted.current = false
      unsubscribe()
      window.removeEventListener('pagehide', revokeOnLeave)
      revokeOnLeave()
    }
  }, [logout])

  async function revoke(): Promise<boolean> {
    const generation = temporarySession.current
    temporarySession.current = null
    setPassword('')
    setChallengeId('')
    setCode('')
    if (generation !== null && generation !== getSessionGeneration()) {
      needsLogout.current = false
      return true
    }
    if (generation === null && !needsLogout.current) return true
    needsLogout.current = true
    try {
      await logout()
      needsLogout.current = false
      return true
    } catch (error: unknown) {
      setStep('cleanup')
      setStatus(error instanceof Error ? error.message : '临时会话退出尚未确认，请重试退出')
      return false
    }
  }

  async function close(destination: 'password' | 'email' = 'password') {
    if (lock.current || sendingCode) return
    returnTo.current = destination
    lock.current = true
    setBusy(true)
    try {
      if (await revoke()) {
        if (destination === 'email') onBack()
        else onClose()
      }
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  function reportError(error: unknown) {
    if (error instanceof ApiError && error.retryAfter) onRateLimit(error.retryAfter)
    setStatus(error instanceof Error ? error.message : '操作失败，请稍后重试')
  }

  async function verifyAccount(): Promise<boolean> {
    if (step === 'email') {
      const current = temporarySession.current === getSessionGeneration()
      if (current) setStatus('')
      return current
    }
    if (step !== 'account' || lock.current || remaining || (turnstileRequired && !token)) return false
    if (!account.trim() || !password) {
      setStatus('请填写登录账号和当前密码')
      return false
    }
    lock.current = true
    setBusy(true)
    setStatus('')
    try {
      const user = await loginAccount(account.trim(), password, token)
      setPassword('')
      temporarySession.current = getSessionGeneration()
      if (!mounted.current) {
        await revoke()
        return false
      }
      if (user.role !== 'admin' && user.role !== role) {
        if (await revoke()) {
          setStep('account')
          setStatus(`该账号为${user.role === 'teacher' ? '教师' : '学生'}账号，请关闭弹窗并选择对应身份后重新验证`)
        }
        return false
      }
      if (user.email?.trim() && user.emailVerified) {
        if (await revoke()) {
          setStep('existing')
          setStatus('该账号已绑定邮箱，请使用邮箱登录；如需管理邮箱，请先登录后前往个人设置')
        }
        return false
      }
      setStep('email')
      return true
    } catch (error: unknown) {
      reportError(error)
      // 验证成功后的异常也必须撤销已经安装的临时凭据。
      if (temporarySession.current !== null) await revoke()
      return false
    } finally {
      setToken('')
      setEpoch(value => value + 1)
      lock.current = false
      setBusy(false)
    }
  }

  async function submitBinding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (step !== 'email' || lock.current || sendingCode || remaining) return
    const generation = temporarySession.current
    if (generation === null || generation !== getSessionGeneration()) {
      setStatus('临时会话已结束，请关闭弹窗后重新验证账号')
      setStep('ended')
      return
    }
    if (!challengeId || !/^\d{6}$/.test(code)) {
      setStatus('请发送并填写 6 位邮箱验证码')
      return
    }
    lock.current = true
    setBusy(true)
    setStatus('')
    try {
      await bindEmail({ email: email.trim(), challenge_id: challengeId, code })
      if (mounted.current && getSessionGeneration() === generation + 1) onBound()
    } catch (error: unknown) {
      reportError(error)
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  return <ConfigurationDialog
    title="绑定邮箱"
    description={step === 'account' || step === 'email' ? '填写账号、密码和邮箱，发送验证码后完成绑定。' : '绑定成功后所有设备退出，请重新登录。'}
    busy={requestBusy}
    onClose={() => void close()}
    footer={<button className="auth-link login-link" type="button" disabled={requestBusy} onClick={() => void close('email')}>返回邮箱登录</button>}
  >
    <div className="auth-dialog">
      {(step === 'account' || step === 'email') && <form className="auth-dialog-form" aria-label="绑定邮箱" onSubmit={event => void submitBinding(event)}>
        <fieldset className="auth-fields" disabled={requestBusy}>
          {step === 'account' ? <>
            <label className="auth-field"><span>登录账号</span><input aria-label="登录账号" placeholder="请输入管理员分配的登录账号" autoComplete="username" required maxLength={64} value={account} onChange={event => setAccount(event.target.value)} /></label>
            <label className="auth-field"><span>当前密码</span><input aria-label="当前密码" type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} /></label>
          </> : <p className="auth-binding-account" role="status">账号 {account.trim()} 已验证，可继续绑定邮箱。</p>}
          <label className="auth-field"><span>新邮箱</span><input aria-label="新邮箱" type="email" autoComplete="email" placeholder="请输入要绑定的邮箱" required maxLength={128} value={email} onChange={event => { setEmail(event.target.value); setChallengeId(''); setCode('') }} /></label>
          {step === 'account' && <Turnstile key={epoch} action="password_login" onToken={setToken} onRequired={setTurnstileRequired} />}
          <EmailCodeFields
            email={email}
            purpose="email_bind"
            beforeSend={verifyAccount}
            sendDisabled={remaining > 0 || (step === 'account' && turnstileRequired && !token)}
            revealCodeAfterSend
            minimumRetrySeconds={60}
            onProof={(id, value) => { setChallengeId(id); setCode(value) }}
            onBusyChange={setSendingCode}
          />
        </fieldset>
        {remaining > 0 && <p className="auth-help" role="status">{remaining} 秒后可重试</p>}
        {challengeId && <>
          <p className="auth-help">绑定成功后所有设备退出，请重新登录。</p>
          <button className="auth-primary" type="submit" disabled={requestBusy || remaining > 0}>{requestBusy ? '处理中…' : remaining ? `${remaining} 秒后重试` : '绑定并返回登录'}</button>
        </>}
        {status && <p className="auth-notice" role="status">{status}</p>}
      </form>}
      {step !== 'account' && step !== 'email' && status && <p className="auth-notice" role="status">{status}</p>}
      {step === 'cleanup' && <div className="auth-dialog-help">
        {logoutError && <p role="alert">{logoutError}</p>}
        <button className="auth-secondary" type="button" disabled={requestBusy} onClick={() => void close(returnTo.current)}>重试退出</button>
      </div>}
    </div>
  </ConfigurationDialog>
}
