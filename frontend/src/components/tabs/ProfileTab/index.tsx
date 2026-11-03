/** 个人中心页：教师信息展示与编辑、头像上传裁剪、模型配置与安全设置（演示） */
import { useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import {
  BadgeCheck,
  Building2,
  KeyRound,
  Pencil,
  Save,
  ShieldCheck,
  User,
  UserRound,
} from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import AvatarCropModal from '../../ui/AvatarCropModal'

export default function ProfileTab() {
  const { profile, updateProfile, showToast } = useApp()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ name: profile.name, gender: profile.gender, phone: profile.phone, email: profile.email })
  const [modelMode, setModelMode] = useState<'default' | 'custom'>('default')
  const [cropSrc, setCropSrc] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const startEdit = () => {
    setDraft({ name: profile.name, gender: profile.gender, phone: profile.phone, email: profile.email })
    setEditing(true)
  }

  const saveEdit = () => {
    if (!draft.name.trim()) {
      showToast('昵称不能为空')
      return
    }
    if (!/^1\d{10}$/.test(draft.phone.trim())) {
      showToast('请输入正确的 11 位手机号码')
      return
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(draft.email.trim())) {
      showToast('请输入正确的邮箱地址')
      return
    }
    updateProfile({
      name: draft.name.trim(),
      gender: draft.gender,
      phone: draft.phone.trim(),
      email: draft.email.trim(),
    })
    setEditing(false)
    showToast('个人信息已保存')
  }

  const onPickFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!/^image\/(png|jpe?g|webp)$/.test(file.type)) {
      showToast('仅支持 PNG / JPG / WebP 图片')
      return
    }
    const reader = new FileReader()
    reader.onload = () => setCropSrc(String(reader.result))
    reader.readAsDataURL(file)
    e.target.value = ''
  }

  const patchDraft = (patch: Partial<typeof draft>) => setDraft((prev) => ({ ...prev, ...patch }))

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
        {/* 头像：悬停显示编辑，点击上传裁剪 */}
        <div
          className="group relative h-[104px] w-[104px] shrink-0 cursor-pointer overflow-visible"
          onClick={() => fileInput.current?.click()}
          title="点击更换头像"
        >
          {profile.avatar ? (
            <img
              src={profile.avatar}
              alt={`${profile.identity}头像`}
              className="h-[96px] w-[96px] rounded-full border border-line/60 object-cover"
            />
          ) : (
            <span className="flex h-[96px] w-[96px] items-center justify-center rounded-full border border-line/60 bg-primary-light text-3xl font-semibold text-primary">
              {profile.name.charAt(0)}
            </span>
          )}
          <BadgeCheck
            size={22}
            className="absolute -bottom-1 right-0 rounded-full bg-white text-primary"
            fill="white"
          />
          <div className="absolute inset-0 flex items-center justify-center rounded-2xl bg-black/45 opacity-0 transition-opacity group-hover:opacity-100">
            <span className="flex items-center gap-1 text-xs font-medium text-white">
              <Pencil size={12} />
              编辑
            </span>
          </div>
        </div>
        <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={onPickFile} />

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
              onClick={saveEdit}
              className="inline-flex items-center gap-1 rounded-lg bg-primary px-3.5 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#1a5fe6]"
            >
              <Save size={13} />
              保存
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

        <div className="grid grid-cols-2 gap-x-10 gap-y-5 px-2">
          <div className="flex items-center gap-6">
            <span className="w-16 shrink-0 text-sm text-ink-3">昵称</span>
            {editing ? (
              <input type="text" value={draft.name} maxLength={20} onChange={(e) => patchDraft({ name: e.target.value })} className={fieldCls} />
            ) : (
              <span className="text-sm text-ink">{profile.name}</span>
            )}
          </div>
          <div className="flex items-center gap-6">
            <span className="w-16 shrink-0 text-sm text-ink-3">性别</span>
            {editing ? (
              <select value={draft.gender} onChange={(e) => patchDraft({ gender: e.target.value as '男' | '女' })} className={fieldCls}>
                <option value="男">男</option>
                <option value="女">女</option>
              </select>
            ) : (
              <span className="flex items-center gap-1.5 text-sm text-ink">
                <UserRound size={14} className="text-primary" />
                {profile.gender}
              </span>
            )}
          </div>
          <div className="flex items-center gap-6">
            <span className="w-16 shrink-0 text-sm text-ink-3">手机号码</span>
            {editing ? (
              <input type="tel" value={draft.phone} maxLength={11} onChange={(e) => patchDraft({ phone: e.target.value })} className={fieldCls} />
            ) : (
              <span className="text-sm text-ink">{profile.phone}</span>
            )}
          </div>
          <div className="flex items-center gap-6">
            <span className="w-16 shrink-0 text-sm text-ink-3">邮箱</span>
            {editing ? (
              <input type="email" value={draft.email} onChange={(e) => patchDraft({ email: e.target.value })} className={fieldCls} />
            ) : (
              <span className="text-sm text-ink">{profile.email}</span>
            )}
          </div>
        </div>
      </div>

      {/* 模型配置 */}
      <div className="mb-4 rounded-xl border border-line/70 bg-white p-5 shadow-[0_4px_16px_rgba(30,90,180,0.05)]">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-bold text-ink">
            <span className="h-3.5 w-1 rounded-full bg-primary" />
            模型配置
          </h3>
          <button
            type="button"
            onClick={() => showToast('自定义模型配置将在后续版本开放')}
            className="rounded-lg border border-primary/30 bg-primary-light/50 px-3.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary-light"
          >
            自定义配置
          </button>
        </div>
        <div className="space-y-3 px-2">
          {(
            [
              { key: 'default', title: '系统默认', desc: '使用平台默认的模型配置，满足大部分使用场景' },
              { key: 'custom', title: '自定义', desc: '根据个人需求配置模型参数' },
            ] as const
          ).map((opt) => (
            <button
              key={opt.key}
              type="button"
              onClick={() => setModelMode(opt.key)}
              className="flex w-full items-start gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-page"
            >
              <span
                className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 ${
                  modelMode === opt.key ? 'border-primary' : 'border-ink-3/60'
                }`}
              >
                {modelMode === opt.key && <span className="h-2 w-2 rounded-full bg-primary" />}
              </span>
              <span>
                <span className="block text-sm text-ink">{opt.title}</span>
                <span className="mt-0.5 block text-xs text-ink-3">{opt.desc}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* 其他设置 */}
      <div className="rounded-xl border border-line/70 bg-white p-5 shadow-[0_4px_16px_rgba(30,90,180,0.05)]">
        <h3 className="mb-4 flex items-center gap-2 text-sm font-bold text-ink">
          <span className="h-3.5 w-1 rounded-full bg-primary" />
          其他设置
        </h3>
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-2.5">
            <KeyRound size={16} className="text-primary" />
            <div>
              <p className="text-sm text-ink">修改密码</p>
              <p className="mt-0.5 text-xs text-ink-3">定期修改密码，保障账号安全</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => showToast('修改密码功能将在后端接入后开放')}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-[0_4px_12px_rgba(30,111,255,0.30)] transition-all hover:bg-[#1a5fe6] active:scale-[0.97]"
          >
            <KeyRound size={14} />
            修改密码
          </button>
        </div>
      </div>

      {/* 头像裁剪弹窗 */}
      {cropSrc && (
        <AvatarCropModal
          imageSrc={cropSrc}
          fileName="avatar"
          onClose={() => setCropSrc(null)}
          onConfirm={(dataUrl) => {
            updateProfile({ avatar: dataUrl })
            setCropSrc(null)
            showToast('头像已更新')
          }}
        />
      )}
    </div>
  )
}
