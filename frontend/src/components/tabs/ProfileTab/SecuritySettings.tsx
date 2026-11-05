/** 安全资料独立提交；不允许普通资料接口改邮箱或学工号。 */
import { useState } from 'react'
import { changeEmail, changeUserNo, startEmailChange } from '../../../api/auth'
import { useAuth } from '../../../store/AuthContext'
import { EmailCodeFields } from '../../auth/EmailCodeFields'
export function SecuritySettings() {
  const { user, signIn } = useAuth()
  const [userNo, setUserNo] = useState(user?.userNo ?? '')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [transaction, setTransaction] = useState('')
  const [expiresAt, setExpiresAt] = useState(0)
  const [oldProof, setOldProof] = useState({ id: '', code: '' })
  const [newProof, setNewProof] = useState({ id: '', code: '' })
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  async function saveUserNo(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setStatus('')
    try { const fresh = await changeUserNo(userNo.trim() || null, password); setPassword(''); signIn(fresh); setStatus('学工号已更新；仍可使用邮箱验证码登录') } catch (error) { setStatus(error instanceof Error ? error.message : '更新失败') } finally { setBusy(false) }
  }
  async function begin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    setBusy(true); setStatus(''); setTransaction(''); setOldProof({ id: '', code: '' }); setNewProof({ id: '', code: '' })
    try { const result = await startEmailChange(email.trim()); setTransaction(result.change_id); setExpiresAt(Date.now() + result.expires_in * 1000); setStatus('请分别验证旧邮箱与新邮箱；事务 10 分钟内有效') } catch (error) { setStatus(error instanceof Error ? error.message : '无法开始换绑') } finally { setBusy(false) }
  }
  async function confirm(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return
    if (Date.now() >= expiresAt) { setStatus('换绑事务已过期，请重新开始'); setTransaction(''); return }
    if (!oldProof.id || !newProof.id || !/^\d{6}$/.test(oldProof.code) || !/^\d{6}$/.test(newProof.code)) { setStatus('请完成旧、新邮箱两次验证码验证'); return }
    setBusy(true); setStatus('')
    try { await changeEmail({ change_id: transaction, old_challenge_id: oldProof.id, old_code: oldProof.code, new_challenge_id: newProof.id, new_code: newProof.code }) } catch (error) { setStatus(error instanceof Error ? error.message : '换绑失败') } finally { setBusy(false) }
  }
  const field = 'block w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink focus:border-primary'
  const button = 'rounded-lg bg-primary px-4 py-2 text-sm text-white disabled:opacity-50'
  return <section className="mb-4 rounded-xl border border-line/70 bg-white p-5 shadow-[0_4px_16px_rgba(30,90,180,0.05)]" aria-label="账号安全">
    <h3 className="mb-4 text-sm font-bold text-ink">账号安全</h3>
    <div className="grid gap-6 lg:grid-cols-2">
      <form onSubmit={event => void saveUserNo(event)} className="space-y-3"><fieldset disabled={busy} className="space-y-3"><legend className="mb-2 text-sm font-medium">维护学工号</legend><p className="text-xs text-ink-3">保留前导零，区分大小写；留空表示移除，不影响邮箱登录。</p><label className="block text-sm">学工号<input className={field} autoComplete="username" value={userNo} maxLength={32} onChange={event => setUserNo(event.target.value)} /></label><label className="block text-sm">当前密码<input className={field} type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} /></label><button className={button} disabled={busy} type="submit">保存学工号</button></fieldset></form>
      <div className="space-y-3"><h4 className="text-sm font-medium">换绑邮箱</h4><p className="text-xs text-ink-3">当前邮箱：{user?.email}。需验证旧、新两个邮箱；完成后所有设备重新登录。</p>
        {!transaction ? <form onSubmit={event => void begin(event)} className="space-y-3"><label className="block text-sm">新邮箱<input className={field} type="email" required disabled={busy} value={email} onChange={event => setEmail(event.target.value)} /></label><button className={button} disabled={busy} type="submit">开始换绑</button></form> : <form onSubmit={event => void confirm(event)}><fieldset className="space-y-4" disabled={busy}><legend className="mb-2 text-sm">新邮箱：{email}</legend><EmailCodeFields email={user?.email ?? ''} purpose="email_change_old" changeId={transaction} label="旧邮箱验证码" onProof={(id, code) => setOldProof({ id, code })} /><EmailCodeFields email={email.trim()} purpose="email_change_new" changeId={transaction} label="新邮箱验证码" onProof={(id, code) => setNewProof({ id, code })} /><div className="flex gap-3"><button type="submit" className={button} disabled={busy}>确认换绑并重新登录</button><button type="button" disabled={busy} onClick={() => { setTransaction(''); setOldProof({ id: '', code: '' }); setNewProof({ id: '', code: '' }); setStatus('') }}>取消换绑</button></div></fieldset></form>}
      </div>
    </div>
    {status && <p className="mt-4 rounded-lg bg-primary-light p-3 text-sm text-ink" role="status">{status}</p>}
  </section>
}
