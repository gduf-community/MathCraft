import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, loginEmail, resetPassword, validateNewPassword } from '../../api/auth'
import type { AuthUser } from '../../api/auth'
import { ConfigurationDialog } from '../ui/ConfigurationDialog'
import { EmailCodeFields } from './EmailCodeFields'

interface AuthDialogProps {
  kind: 'email' | 'reset'
  adminContact: string
  now: number
  retryAt: number
  onRateLimit: (seconds: number) => void
  onAuthenticated: (user: AuthUser) => Promise<void>
  onClose: () => void
  onBindEmail: () => void
  onReset: () => void
}

/** 邮箱登录与找回密码独立于主卡片；卸载时丢弃验证码和密码。 */
export function AuthDialog({
  kind, adminContact, now, retryAt, onRateLimit, onAuthenticated, onClose, onBindEmail, onReset,
}: AuthDialogProps) {
  const [step, setStep] = useState<'choice' | 'admin' | 'email'>(kind === 'email' ? 'email' : 'choice')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [challengeId, setChallengeId] = useState('')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [sendingCode, setSendingCode] = useState(false)
  const [status, setStatus] = useState('')
  const emailRef = useRef<HTMLInputElement>(null)
  const choiceRef = useRef<HTMLButtonElement>(null)
  const requestBusy = busy || sendingCode
  const isReset = kind === 'reset'
  const remaining = Math.max(0, Math.ceil((retryAt - now) / 1000))
  const adminEmail = adminContact.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)?.[0]

  function close() {
    if (requestBusy) return
    setPassword('')
    setConfirm('')
    setCode('')
    setChallengeId('')
    onClose()
  }

  function choose(next: 'choice' | 'admin' | 'email') {
    if (requestBusy) return
    setStep(next)
    setPassword('')
    setConfirm('')
    setCode('')
    setChallengeId('')
    setStatus('')
    // 切换内容后移入新表单；返回选择时落在第一个选项。
    window.requestAnimationFrame(() => {
      if (next === 'email') emailRef.current?.focus()
      else choiceRef.current?.focus()
    })
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (requestBusy || remaining) return
    if (isReset) {
      const error = validateNewPassword(password)
      if (error || password !== confirm) {
        setStatus(error ?? '两次密码输入不一致')
        return
      }
    }
    if (!challengeId || !/^\d{6}$/.test(code)) {
      setStatus('请发送并填写 6 位邮箱验证码')
      return
    }
    setBusy(true)
    setStatus('')
    try {
      const proof = { email: email.trim(), challenge_id: challengeId, code }
      if (isReset) {
        await resetPassword({ ...proof, new_password: password, confirm_password: confirm })
        onReset()
      } else {
        await onAuthenticated(await loginEmail(proof))
      }
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.retryAfter) onRateLimit(reason.retryAfter)
      setStatus(reason instanceof Error ? reason.message : '认证失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  return <ConfigurationDialog
    title={isReset ? '找回密码' : '邮箱登录'}
    description={isReset ? '请选择适合你的密码找回方式。' : '使用已绑定并验证的邮箱登录当前选择的身份。'}
    busy={requestBusy}
    onClose={close}
    footer={<button className="auth-link login-link" type="button" disabled={requestBusy} onClick={close}>返回密码登录</button>}
  >
    <div className="auth-dialog">
      {step === 'choice' && <div className="auth-recovery-options">
        <button ref={choiceRef} className="auth-recovery-option" type="button" onClick={() => choose('admin')}>
          <span>联系管理员重置密码</span>
          <span aria-hidden="true">由学校或平台管理员协助处理</span>
        </button>
        <button className="auth-recovery-option" type="button" onClick={() => choose('email')}>
          <span>通过已绑定邮箱重置密码</span>
          <span aria-hidden="true">验证邮箱后设置新密码</span>
        </button>
      </div>}
      {step === 'admin' && <div className="auth-dialog-help">
        <h3>联系管理员重置密码</h3>
        <p>请联系本校或平台管理员，核实账号身份后协助重置密码。</p>
        <p>{adminContact}</p>
        {adminEmail && <>
          <p>管理员邮箱：<span>{adminEmail}</span></p>
          <a className="auth-secondary" href={`mailto:${adminEmail}`}>发邮件给管理员</a>
        </>}
        <button ref={choiceRef} className="auth-link login-link" type="button" onClick={() => choose('choice')}>返回选择找回方式</button>
      </div>}
      {step === 'email' && <form className="auth-dialog-form" onSubmit={event => void submit(event)}>
        <fieldset className="auth-fields" disabled={requestBusy}>
          <label className="auth-field"><span>邮箱</span><input ref={emailRef} aria-label="邮箱" type="email" autoComplete="email" placeholder="请输入已绑定的邮箱" required maxLength={128} value={email} onChange={event => { setEmail(event.target.value); setChallengeId(''); setCode('') }} /></label>
          {isReset && <>
            <label className="auth-field"><span>新密码</span><input aria-label="新密码" type="password" autoComplete="new-password" required value={password} onChange={event => setPassword(event.target.value)} /></label>
            <label className="auth-field"><span>确认新密码</span><input aria-label="确认新密码" type="password" autoComplete="new-password" required value={confirm} onChange={event => setConfirm(event.target.value)} /></label>
            <p className="auth-help">8–64 字符，UTF-8 不超过 72 字节</p>
          </>}
          <EmailCodeFields
            key={email}
            email={email}
            purpose={isReset ? 'reset_password' : 'login'}
            onProof={(id, value) => { setChallengeId(id); setCode(value) }}
            onBusyChange={setSendingCode}
          />
        </fieldset>
        {status && <p className="auth-notice" role="status">{status}</p>}
        <button className="auth-primary" type="submit" disabled={requestBusy || remaining > 0}>
          {requestBusy ? '处理中…' : remaining ? `${remaining} 秒后重试` : isReset ? '重置密码' : '登录'}
        </button>
        {!isReset && <p className="auth-help">尚未绑定邮箱？<button className="auth-link login-link" type="button" disabled={requestBusy} onClick={onBindEmail}>先绑定</button></p>}
        {isReset && <button className="auth-link login-link" type="button" disabled={requestBusy} onClick={() => choose('choice')}>返回选择找回方式</button>}
      </form>}
    </div>
  </ConfigurationDialog>
}
