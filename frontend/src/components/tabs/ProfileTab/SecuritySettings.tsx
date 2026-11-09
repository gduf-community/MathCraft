/** 账号安全资料：学工号仅作为可选资料，邮箱支持绑定、换绑和解绑。 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { bindEmail, changeEmail, changeUserNo, startEmailChange, unbindEmail } from '../../../api/auth'
import { useAuth } from '../../../store/AuthContext'
import { EmailCodeFields } from '../../auth/EmailCodeFields'

interface Proof { id: string; code: string }

export function SecuritySettings() {
  const { user, signIn, setAuthNotice } = useAuth()
  const [userNo, setUserNo] = useState(user?.userNo ?? '')
  const [userNoPassword, setUserNoPassword] = useState('')
  const [email, setEmail] = useState('')
  const [emailPassword, setEmailPassword] = useState('')
  const [bindProof, setBindProof] = useState<Proof>({ id: '', code: '' })
  const [transaction, setTransaction] = useState('')
  const [expiresAt, setExpiresAt] = useState(0)
  const [oldProof, setOldProof] = useState<Proof>({ id: '', code: '' })
  const [newProof, setNewProof] = useState<Proof>({ id: '', code: '' })
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const boundEmail = user?.email?.trim() ?? ''
  const verifiedEmail = Boolean(boundEmail && user?.emailVerified)

  async function saveUserNo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setStatus('')
    try {
      const fresh = await changeUserNo(userNo.trim() || null, userNoPassword)
      setUserNoPassword('')
      signIn(fresh)
      setStatus('学工号资料已更新；学工号不用于登录')
    } catch (error: unknown) {
      setStatus(error instanceof Error ? error.message : '更新失败')
    } finally { setBusy(false) }
  }

  async function confirmEmailBinding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    if (!email.trim() || !emailPassword || !bindProof.id || !/^\d{6}$/.test(bindProof.code)) {
      setStatus('请填写邮箱、当前密码并完成邮箱验证码')
      return
    }
    setBusy(true)
    setStatus('')
    try {
      setAuthNotice('邮箱已更新，所有设备已退出，请使用账号密码重新登录')
      await bindEmail({ email: email.trim(), current_password: emailPassword, challenge_id: bindProof.id, code: bindProof.code })
    } catch (error: unknown) {
      setAuthNotice('')
      setStatus(error instanceof Error ? error.message : '邮箱绑定失败')
    } finally { setBusy(false) }
  }

  async function beginEmailChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setStatus('')
    setTransaction('')
    setOldProof({ id: '', code: '' })
    setNewProof({ id: '', code: '' })
    try {
      const result = await startEmailChange(email.trim())
      setTransaction(result.change_id)
      setExpiresAt(Date.now() + result.expires_in * 1000)
      setStatus('请分别验证旧邮箱与新邮箱；事务 10 分钟内有效')
    } catch (error: unknown) {
      setStatus(error instanceof Error ? error.message : '无法开始换绑')
    } finally { setBusy(false) }
  }

  async function confirmEmailChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    if (Date.now() >= expiresAt) {
      setTransaction('')
      setStatus('换绑事务已过期，请重新开始')
      return
    }
    if (!oldProof.id || !newProof.id || !/^\d{6}$/.test(oldProof.code) || !/^\d{6}$/.test(newProof.code)) {
      setStatus('请完成旧、新邮箱两次验证码验证')
      return
    }
    setBusy(true)
    setStatus('')
    try {
      setAuthNotice('邮箱已更新，所有设备已退出，请使用账号密码重新登录')
      await changeEmail({ change_id: transaction, old_challenge_id: oldProof.id, old_code: oldProof.code, new_challenge_id: newProof.id, new_code: newProof.code })
    } catch (error: unknown) {
      setAuthNotice('')
      setStatus(error instanceof Error ? error.message : '换绑失败')
    } finally { setBusy(false) }
  }

  async function removeEmail() {
    if (busy || !emailPassword) {
      setStatus('请先输入当前密码')
      return
    }
    if (!window.confirm('解绑后无法使用邮箱登录和邮箱找回密码，仍可使用账号密码登录。确定继续吗？')) return
    setBusy(true)
    setStatus('')
    try {
      setAuthNotice('邮箱已解绑，所有设备已退出，请使用账号密码重新登录')
      await unbindEmail(emailPassword)
    } catch (error: unknown) {
      setAuthNotice('')
      setStatus(error instanceof Error ? error.message : '解绑失败')
    } finally { setBusy(false) }
  }

  const field = 'block min-h-11 w-full min-w-0 rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink focus:border-primary'
  const button = 'min-h-11 rounded-lg bg-primary px-4 py-2 text-sm text-white disabled:opacity-50'
  const emailLabel = verifiedEmail ? '换绑邮箱' : boundEmail ? '重新验证邮箱' : '绑定邮箱'

  return <section className="mb-4 rounded-xl border border-line/70 bg-white p-5 shadow-[0_4px_16px_rgba(30,90,180,0.05)]" aria-label="账号安全">
    <h3 className="mb-4 text-sm font-bold text-ink">账号安全</h3>
    <div className="grid gap-6 lg:grid-cols-2">
      <form onSubmit={event => void saveUserNo(event)} className="space-y-3">
        <fieldset disabled={busy} className="space-y-3">
          <legend className="mb-2 text-sm font-medium">维护学工号资料</legend>
          <p className="text-xs text-ink-3">学工号保留前导零，仅作为个人资料，不再用于登录。</p>
          <label className="block text-sm">学工号<input className={field} autoComplete="off" value={userNo} maxLength={32} onChange={event => setUserNo(event.target.value)} /></label>
          <label className="block text-sm">当前密码<input className={field} type="password" autoComplete="current-password" required value={userNoPassword} onChange={event => setUserNoPassword(event.target.value)} /></label>
          <button className={button} disabled={busy} type="submit">保存学工号资料</button>
        </fieldset>
      </form>

      <div className="min-w-0 space-y-3">
        <h4 className="text-sm font-medium">邮箱设置</h4>
        <p className="break-all text-xs text-ink-3">当前邮箱：{boundEmail || '未绑定'}{boundEmail && !verifiedEmail ? '（待验证）' : ''}。邮箱为可选配置。</p>
        {!verifiedEmail && <form onSubmit={event => void confirmEmailBinding(event)} className="space-y-3">
          <label className="block text-sm">{emailLabel}<input className={field} type="email" required disabled={busy} value={email} onChange={event => { setEmail(event.target.value); setBindProof({ id: '', code: '' }) }} /></label>
          <label className="block text-sm">当前密码<input className={field} type="password" autoComplete="current-password" required disabled={busy} value={emailPassword} onChange={event => setEmailPassword(event.target.value)} /></label>
          <fieldset disabled={busy}><EmailCodeFields key={email.trim()} email={email.trim()} purpose="email_bind" onProof={(id, code) => setBindProof({ id, code })} /></fieldset>
          <button className={button} disabled={busy} type="submit">绑定并重新登录</button>
        </form>}
        {verifiedEmail && !transaction && <>
          <form onSubmit={event => void beginEmailChange(event)} className="space-y-3">
            <label className="block text-sm">新邮箱<input className={field} type="email" required disabled={busy} value={email} onChange={event => setEmail(event.target.value)} /></label>
            <button className={button} disabled={busy} type="submit">开始换绑</button>
          </form>
          <label className="block text-sm">当前密码<input className={field} type="password" autoComplete="current-password" disabled={busy} value={emailPassword} onChange={event => setEmailPassword(event.target.value)} /></label>
        </>}
        {boundEmail && !transaction && <button className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-ink-2 disabled:opacity-50" disabled={busy} type="button" onClick={() => void removeEmail()}>解绑邮箱</button>}
        {verifiedEmail && transaction && <form onSubmit={event => void confirmEmailChange(event)}>
          <fieldset className="space-y-4" disabled={busy}>
            <legend className="mb-2 text-sm">新邮箱：{email}</legend>
            <EmailCodeFields email={boundEmail} purpose="email_change_old" changeId={transaction} label="旧邮箱验证码" onProof={(id, code) => setOldProof({ id, code })} />
            <EmailCodeFields email={email.trim()} purpose="email_change_new" changeId={transaction} label="新邮箱验证码" onProof={(id, code) => setNewProof({ id, code })} />
            <div className="flex gap-3"><button type="submit" className={button} disabled={busy}>确认换绑并重新登录</button><button type="button" disabled={busy} onClick={() => { setTransaction(''); setOldProof({ id: '', code: '' }); setNewProof({ id: '', code: '' }); setStatus('') }}>取消换绑</button></div>
          </fieldset>
        </form>}
      </div>
    </div>
    {status && <p className="mt-4 rounded-lg bg-primary-light p-3 text-sm text-ink" role="status">{status}</p>}
  </section>
}
