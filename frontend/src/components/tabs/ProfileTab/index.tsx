/** 个人中心页：个人资料与账号安全。头像为系统默认，不可修改。 */
import { useRef, useState } from 'react'
import {
  BadgeCheck,
  Building2,
  Loader2,
  Pencil,
  Save,
  ShieldCheck,
  User,
  UserRound,
  X,
} from 'lucide-react'
import { useApp } from '../../../store/AppContext'

import { SecuritySettings } from './SecuritySettings'
import { changePasswordCurrent, validateNewPassword } from '../../../api/auth'
import { useAuth } from '../../../store/AuthContext'
import { getSessionGeneration } from '../../../api/session'

export default function ProfileTab() {
  const { profile, updateProfile, showToast } = useApp()
  const { user, setAuthNotice } = useAuth()

  const session = useRef(getSessionGeneration())
  const [profileError, setProfileError] = useState('')
  const [pwdError, setPwdError] = useState('')
  const reportProfileError = (message: string) => { setProfileError(message); showToast(message, 'error') }
  const reportPasswordError = (message: string) => { setPwdError(message); showToast(message, 'error') }

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ name: profile.name, gender: profile.gender, phone: profile.phone, email: profile.email })
  const [savingProfile, setSavingProfile] = useState(false)
  const [pwdOpen, setPwdOpen] = useState(false)
  const [pwdOld, setPwdOld] = useState('')
  const [pwdNew, setPwdNew] = useState('')
  const [pwdConfirm, setPwdConfirm] = useState('')
  const [savingPwd, setSavingPwd] = useState(false)

  const startEdit = () => {
    setProfileError('')
    setDraft({ name: profile.name, gender: profile.gender, phone: profile.phone, email: profile.email })
    setEditing(true)
  }

  const saveEdit = async () => {
    if (savingProfile) return
    if (!draft.name.trim()) { reportProfileError('昵称不能为空'); return }
    if (draft.phone.trim() && !/^1[0-9]{10}$/.test(draft.phone.trim())) { reportProfileError('请输入正确的 11 位手机号码'); return }
    setProfileError('')
    setSavingProfile(true)
    try {
      await updateProfile({ name: draft.name.trim(), gender: draft.gender, phone: draft.phone.trim() })
      setEditing(false)
      showToast('个人信息已保存', 'success')
    } catch (error) { reportProfileError(error instanceof Error ? error.message : '保存失败') }
    finally { setSavingProfile(false) }
  }

  const patchDraft = (patch: Partial<typeof draft>) => setDraft((prev) => ({ ...prev, ...patch }))

  const submitPassword = async () => {
    if (savingPwd) return
    if (!pwdOld) { reportPasswordError('请输入当前密码'); return }
    setPwdError('')
    const passwordError = validateNewPassword(pwdNew)
    if (passwordError) { reportPasswordError(passwordError); return }
    if (pwdNew !== pwdConfirm) {
      reportPasswordError('两次输入的新密码不一致')
      return
    }
    setSavingPwd(true)
    try {
      await changePasswordCurrent(pwdOld, pwdNew, pwdConfirm)
      if (getSessionGeneration() === session.current + 1) setAuthNotice('密码已修改，请使用新密码重新登录')
      setPwdOpen(false)
      setPwdOld(''); setPwdNew(''); setPwdConfirm('')
    } catch (err) {
      reportPasswordError(err instanceof Error ? err.message : '修改密码失败')
    } finally {
      setSavingPwd(false)
    }
  }

  const fieldCls =
    'block w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary'

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-5">
      {/* 页面小标题 */}
      <div className="mb-4 flex items-center gap-1.5 border-b border-line pb-3">
        <User size={15} className="text-primary" />
        <span className="relative text-sm font-semibold text-primary">
          个人中心
          <span className="absolute inset-x-0 -bottom-3 h-0.5 rounded-full bg-primary" />
        </span>
      </div>

      {/* 头部信息卡 */}
      <div className="mb-4 flex flex-wrap items-center gap-6 rounded-xl border border-line/70 bg-white p-5 shadow-[0_4px_16px_rgba(30,90,180,0.05)]">
        {/* 头像：系统默认（昵称首字），不可修改 */}
        <div className="relative h-[104px] w-[104px] shrink-0">
          <span className="flex h-[96px] w-[96px] items-center justify-center rounded-full border border-line/60 bg-primary-light text-3xl font-semibold text-primary">
            {profile.name.charAt(0)}
          </span>
          <BadgeCheck
            size={22}
            className="absolute -bottom-1 right-0 rounded-full bg-white text-primary"
            fill="white"
          />
        </div>

        <div className="min-w-[180px]">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-ink">{profile.name}</span>
            <span className="rounded bg-primary-light px-1.5 py-0.5 text-xs text-primary">{profile.identity}</span>
          </div>
          <p className="mt-1.5 text-sm text-ink-2">账号 ID：{profile.teacherId}</p>
        </div>

        <div className="space-y-2 border-l border-line/70 pl-6">
          <p className="flex items-center gap-2 text-sm text-ink-2">
            <ShieldCheck size={15} className="text-primary" />
            身份信息：
            <span className="text-ink">{profile.identity}</span>
          </p>
          <p className="flex items-center gap-2 text-sm text-ink-2">
            <Building2 size={15} className="text-primary" />
            学校认证：
            <span className="text-ink">{profile.school}</span>
          </p>
        </div>
      </div>

      {/* 基本信息 */}
      <div className="mb-4 rounded-xl border border-line/70 bg-white p-5 shadow-[0_4px_16px_rgba(30,90,180,0.05)]">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-bold text-ink">
            <span className="h-3.5 w-1 rounded-full bg-primary" />
            基本信息
          </h3>
          {editing ? (
            <button
              type="button"
              onClick={() => void saveEdit()}
              disabled={savingProfile}
              className="inline-flex items-center gap-1 rounded-lg bg-primary px-3.5 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#1a5fe6]"
            >
              <Save size={13} />
              {savingProfile ? '保存中…' : '保存'}
            </button>
          ) : (
            <button
              type="button"
              onClick={startEdit}
              className="inline-flex items-center gap-1 rounded-lg border border-primary/30 bg-primary-light/50 px-3.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary-light"
            >
              <Pencil size={13} />
              编辑
            </button>
          )}
        </div>

        {profileError && <p role="alert" className="mb-3 text-sm text-red-700">{profileError}</p>}
        <div className="grid grid-cols-1 gap-x-10 gap-y-5 px-2 md:grid-cols-2">
          <div className="flex items-center gap-6">
            <span className="w-16 shrink-0 text-sm text-ink-3">登录账号</span>
            <span className="break-all text-sm text-ink">{user?.username}</span>
          </div>
          <div className="flex items-center gap-6">
            <span className="w-16 shrink-0 text-sm text-ink-3">昵称</span>
            {editing ? (
              <input aria-label="昵称" disabled={savingProfile} type="text" value={draft.name} maxLength={20} onChange={(e) => patchDraft({ name: e.target.value })} className={fieldCls} />
            ) : (
              <span className="text-sm text-ink">{profile.name}</span>
            )}
          </div>
          <div className="flex items-center gap-6">
            <span className="w-16 shrink-0 text-sm text-ink-3">性别</span>
            {editing ? (
              <select aria-label="性别" disabled={savingProfile} value={draft.gender} onChange={(e) => {
                const gender = e.target.value
                if (gender === '' || gender === '男' || gender === '女') patchDraft({ gender })
              }} className={fieldCls}>
                <option value="">未填写</option>
                <option value="男">男</option>
                <option value="女">女</option>
              </select>
            ) : (
              <span className="flex items-center gap-1.5 text-sm text-ink">
                <UserRound size={14} className="text-primary" />
                {profile.gender || '未填写'}
              </span>
            )}
          </div>
          <div className="flex items-center gap-6">
            <span className="w-16 shrink-0 text-sm text-ink-3">手机号码</span>
            {editing ? (
              <input aria-label="手机号码（可选，留空清除）" disabled={savingProfile} type="tel" value={draft.phone} maxLength={11} onChange={(e) => patchDraft({ phone: e.target.value })} className={fieldCls} />
            ) : (
              <span className="text-sm text-ink">{profile.phone || '未填写'}</span>
            )}
          </div>
          <div className="flex min-w-0 items-start gap-6">
            <span className="w-16 shrink-0 whitespace-nowrap text-sm text-ink-3">邮箱（可选）</span>
            <span className="min-w-0 break-all text-sm text-ink">{user?.email ? `${user.email}（${user.emailVerified ? '已验证' : '待验证'}，通过账号安全管理）` : '未绑定，可在下方账号安全中绑定'}</span>
          </div>
        </div>
      </div>

      <p className="mb-4 text-xs text-ink-3">性别和手机号码为可选资料；选择“未填写”或清空号码后保存可移除对应资料。</p>

      <SecuritySettings>
        <div className="border-t border-line pt-6">
          <h3 className="mb-4 flex items-center gap-2 text-sm font-bold text-ink">
            <span className="h-3.5 w-1 rounded-full bg-primary" />
            修改密码
          </h3>
          <div className="flex flex-wrap items-center justify-between gap-3 px-2">
            <div>
              <p className="text-sm text-ink">修改密码</p>
              <p className="mt-0.5 text-xs text-ink-3">修改后需要重新登录</p>
            </div>
            <button
              type="button"
              onClick={() => {
                setPwdError('')
                setPwdOld('')
                setPwdNew('')
                setPwdConfirm('')
                setPwdOpen(true)
              }}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-[0_4px_12px_rgba(30,111,255,0.30)] transition-all hover:bg-[#1a5fe6] active:scale-[0.97]"
            >
              修改密码
            </button>
          </div>
        </div>
      </SecuritySettings>

      {/* 修改密码弹窗 */}
      {pwdOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={() => setPwdOpen(false)}>
          <div className="w-[420px] overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <h3 className="text-base font-bold text-ink">修改密码</h3>
              <button type="button" onClick={() => setPwdOpen(false)} className="rounded p-1 text-ink-3 hover:bg-page">
                <X size={18} />
              </button>
            </div>
            <div className="space-y-3 px-5 py-4">
              {pwdError && <p role="alert" className="text-sm text-red-700">{pwdError}</p>}
              <input
                type="password"
                aria-label="当前密码" autoComplete="current-password" value={pwdOld}
                onChange={(e) => setPwdOld(e.target.value)}
                placeholder="当前密码"
                className={fieldCls}
              />
              <input
                type="password"
                aria-label="新密码" autoComplete="new-password" value={pwdNew}
                onChange={(e) => setPwdNew(e.target.value)}
                placeholder="新密码（8–64 字符）"
                className={fieldCls}
              />
              <input
                type="password"
                aria-label="确认新密码" autoComplete="new-password" value={pwdConfirm}
                onChange={(e) => setPwdConfirm(e.target.value)}
                placeholder="确认新密码"
                className={fieldCls}
              />
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
                disabled={savingPwd}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {savingPwd && <Loader2 size={13} className="animate-spin" />}
                确认修改
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
