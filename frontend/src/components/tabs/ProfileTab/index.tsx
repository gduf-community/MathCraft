/** 个人中心页：资料头部、安全管理与 API 配置。头像为系统默认，不可修改。 */
import { useRef, useState } from 'react'
import {
  BadgeCheck,
  Check,
  Headset,
  KeyRound,
  Loader2,
  Lock,
  Pencil,
  User,
  X,
} from 'lucide-react'
import { useApp } from '../../../store/AppContext'

import { ApiConfigCard } from './ApiConfigCard'
import { SecuritySettings } from './SecuritySettings'
import { changePasswordCurrent, validateNewPassword, getAuthConfig } from '../../../api/auth'
import type { AuthConfig } from '../../../api/auth'
import { useAuth } from '../../../store/AuthContext'
import { getSessionGeneration } from '../../../api/session'

export default function ProfileTab() {
  const { profile, updateProfile, showToast } = useApp()
  const { user, setAuthNotice } = useAuth()

  const session = useRef(getSessionGeneration())
  const [pwdError, setPwdError] = useState('')
  const reportPasswordError = (message: string) => { setPwdError(message); showToast(message, 'error') }

  // 昵称编辑：与右上角昵称（profile.name）自动同步
  const [editing, setEditing] = useState(false)
  const [draftName, setDraftName] = useState('')
  const [savingProfile, setSavingProfile] = useState(false)
  const [pwdOpen, setPwdOpen] = useState(false)
  const [pwdOld, setPwdOld] = useState('')
  const [pwdNew, setPwdNew] = useState('')
  const [pwdConfirm, setPwdConfirm] = useState('')
  const [savingPwd, setSavingPwd] = useState(false)
  const [contactOpen, setContactOpen] = useState(false)
  const [contact, setContact] = useState<AuthConfig | null>(null)

  const startEdit = () => {
    setDraftName(profile.name)
    setEditing(true)
  }

  const saveEdit = async () => {
    if (savingProfile) return
    if (!draftName.trim()) { showToast('昵称不能为空', 'error'); return }
    setSavingProfile(true)
    try {
      await updateProfile({ name: draftName.trim() })
      setEditing(false)
      showToast('昵称已保存', 'success')
    } catch (error) {
      showToast(error instanceof Error ? error.message : '保存失败', 'error')
    } finally { setSavingProfile(false) }
  }

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

  const openContact = () => {
    setContactOpen(true)
    if (!contact) {
      void getAuthConfig().then(setContact).catch(() => setContact(null))
    }
  }

  const fieldCls =
    'block w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary'

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-5">
      {/* 页面小标题（复用原标签容器样式） */}
      <div className="mb-4 flex items-center gap-1.5 border-b border-line pb-3">
        <User size={15} className="text-primary" />
        <span className="relative text-sm font-semibold text-primary">
          个人中心
          <span className="absolute inset-x-0 -bottom-3 h-0.5 rounded-full bg-primary" />
        </span>
      </div>

      {/* 头部信息卡 */}
      <div className="mb-4 flex flex-wrap items-center gap-6 rounded-xl border border-line/70 bg-[linear-gradient(90deg,#ffffff_40%,#e9f2ff_100%)] p-5 shadow-[0_4px_16px_rgba(30,90,180,0.05)]">
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
          {editing ? (
            <div className="flex items-center gap-2">
              <input
                aria-label="昵称"
                autoFocus
                disabled={savingProfile}
                type="text"
                value={draftName}
                maxLength={20}
                onChange={(e) => setDraftName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.nativeEvent.isComposing) void saveEdit()
                  if (e.key === 'Escape') setEditing(false)
                }}
                className="w-44 rounded-lg border border-line bg-white px-3 py-1.5 text-lg font-bold text-ink outline-none focus:border-primary"
              />
              <button
                type="button"
                title="保存昵称"
                aria-label="保存昵称"
                disabled={savingProfile}
                onClick={() => void saveEdit()}
                className="rounded-lg bg-primary p-1.5 text-white transition-colors hover:bg-[#1a5fe6] disabled:opacity-60"
              >
                {savingProfile ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
              </button>
              <button
                type="button"
                title="取消"
                aria-label="取消编辑昵称"
                disabled={savingProfile}
                onClick={() => setEditing(false)}
                className="rounded-lg border border-line p-1.5 text-ink-3 transition-colors hover:bg-page"
              >
                <X size={15} />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-2xl font-bold text-ink">{profile.name}</span>
              <button
                type="button"
                title="修改昵称"
                aria-label="修改昵称"
                onClick={startEdit}
                className="rounded p-1 text-ink-3 transition-colors hover:bg-primary-light hover:text-primary"
              >
                <Pencil size={15} />
              </button>
            </div>
          )}
          <div className="mt-2.5 flex items-center gap-2.5 text-sm text-ink-2">
            <span>ID：{profile.teacherId}</span>
            <span className="h-3.5 w-px bg-line" />
            <span className="flex items-center gap-1.5">
              身份：<span className="rounded bg-primary-light px-1.5 py-0.5 text-xs text-primary">{profile.identity}</span>
            </span>
          </div>
          <div className="mt-2.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span className="shrink-0 whitespace-nowrap text-ink-3">登录账号</span>
            <span className="shrink-0 text-ink">{profile.teacherId}</span>
            <span className="h-3.5 w-px shrink-0 bg-line" />
            <span className="shrink-0 whitespace-nowrap text-ink-3">邮箱（可选）</span>
            <span className="min-w-0 break-all text-ink">
              {user?.email
                ? `${user.email}（${user.emailVerified ? '已验证' : '待验证'}，在下方账号安全管理）`
                : '未绑定，可在下方账号安全中绑定'}
            </span>
          </div>
        </div>
      </div>

      {/* 账号安全：学工号资料、邮箱绑定与修改密码入口，回归依赖 region 内顺序 */}
      <SecuritySettings>
        <div className="border-t border-line pt-6">
          {pwdError && <p role="alert" className="mb-3 text-sm text-red-700">{pwdError}</p>}
          <div className="flex flex-wrap items-center gap-3">
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
              <Lock size={14} />
              修改密码
            </button>
            <button
              type="button"
              onClick={openContact}
              className="inline-flex items-center gap-1.5 rounded-lg border border-primary/40 bg-white px-4 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary-light/60"
            >
              <Headset size={14} />
              联系管理员
            </button>
          </div>
        </div>
      </SecuritySettings>

      {/* API 配置 */}
      <ApiConfigCard />

      {/* 修改密码弹窗 */}
      {pwdOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={() => setPwdOpen(false)}>
          <div className="w-[420px] overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <h3 className="flex items-center gap-2 text-base font-bold text-ink">
                <Lock size={16} className="text-primary" />
                修改密码
              </h3>
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

      {/* 联系管理员弹窗 */}
      {contactOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={() => setContactOpen(false)}>
          <div className="w-[420px] overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <h3 className="flex items-center gap-2 text-base font-bold text-ink">
                <Headset size={16} className="text-primary" />
                联系管理员
              </h3>
              <button type="button" onClick={() => setContactOpen(false)} className="rounded p-1 text-ink-3 hover:bg-page">
                <X size={18} />
              </button>
            </div>
            <div className="px-5 py-4">
              <p className="flex items-start gap-2 text-sm leading-6 text-ink-2">
                <KeyRound size={15} className="mt-1 shrink-0 text-primary" />
                {contact?.admin_contact?.trim() || '请联系本校或平台管理员获取账号、重置密码或处理账号问题。'}
              </p>
            </div>
            <div className="flex justify-end border-t border-line px-5 py-3.5">
              <button
                type="button"
                onClick={() => setContactOpen(false)}
                className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 hover:bg-page"
              >
                我知道了
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
