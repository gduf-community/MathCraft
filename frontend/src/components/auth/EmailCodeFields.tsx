/** 发码状态仅绑定当前邮箱/用途；新发码替换旧 challenge。 */
import { useEffect, useState } from 'react'
import { ApiError, sendEmailCode } from '../../api/auth'
import type { CodePurpose, EmailChallenge } from '../../api/auth'
import { Turnstile } from './Turnstile'
interface Props { email: string; purpose: CodePurpose; changeId?: string; label?: string; onProof: (challengeId: string, code: string) => void }
export function EmailCodeFields({ email, purpose, changeId, label = '邮箱验证码', onProof }: Props) {
  const [challenge, setChallenge] = useState<EmailChallenge | null>(null)
  const [code, setCode] = useState('')
  const [token, setToken] = useState('')
  const [epoch, setEpoch] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [retryAt, setRetryAt] = useState(0)
  const [expiresAt, setExpiresAt] = useState(0)
  const [now, setNow] = useState(Date.now)
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(id) }, [])
  const remaining = Math.max(0, Math.ceil((retryAt - now) / 1000))
  const expired = challenge !== null && now >= expiresAt
  async function send() {
    if (busy || remaining || !token) return
    if (email !== undefined && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) { setError('请输入正确的邮箱地址'); return }
    setBusy(true); setError('')
    // 即使发送失败，也不继续向提交方暴露旧 challenge。
    setChallenge(null); setCode(''); onProof('', '')
    try {
      const result = await sendEmailCode({ email: email.trim(), purpose, turnstile_token: token, ...(changeId ? { change_id: changeId } : {}) })
      const time = Date.now()
      setChallenge(result); setRetryAt(time + result.retry_after * 1000); setExpiresAt(time + result.expires_in * 1000); onProof(result.challenge_id, '')
    } catch (reason) {
      if (reason instanceof ApiError && reason.retryAfter) setRetryAt(Date.now() + reason.retryAfter * 1000)
      setError(reason instanceof Error ? reason.message : '发送失败，请重试')
    } finally { setBusy(false); setToken(''); setEpoch(n => n + 1) }
  }
  return <div className="auth-code-block">
    <label className="auth-field"><span>{label}</span><input aria-label={label} value={code} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required disabled={!challenge || expired} onChange={e => { const value = e.target.value.replace(/\D/g, ''); setCode(value); onProof(challenge?.challenge_id ?? '', value) }} /></label>
    <button className="auth-secondary" type="button" disabled={busy || remaining > 0 || !token} onClick={() => void send()}>{busy ? '发送中…' : remaining ? remaining + ' 秒后重发' : challenge ? '重新发送验证码' : '发送验证码'}</button>
    <p className="auth-help" role="status">{expired ? '验证码已过期，请重新发送' : challenge ? '已发送验证码；重发后旧码失效' : '请完成人机验证后发送验证码'}</p>
    {error && <p role="alert" className="auth-error">{error}</p>}
    <Turnstile key={epoch} action="email_code" onToken={setToken} />
  </div>
}
