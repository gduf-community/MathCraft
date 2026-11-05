/** 个人中心页：资料、模型配置、密码修改（全部走后端）。头像为系统默认，不可修改。 */
import { useEffect, useState } from 'react'
import {
  BadgeCheck,
  Building2,
  KeyRound,
  Loader2,
  Pencil,
  Save,
  ShieldCheck,
  User,
  UserRound,
  X,
} from 'lucide-react'
import { useApp } from '../../../store/AppContext'

import {
  getModelSettings,
  saveModelSettings,
  testDeepSeek,
  testMinerU,
  type ModelSettings,
} from '../../../api/backend'
import { SecuritySettings } from './SecuritySettings'
import { changePasswordCurrent, validateNewPassword } from '../../../api/auth'

export default function ProfileTab() {
  const { profile, updateProfile, showToast } = useApp()

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ name: profile.name, gender: profile.gender, phone: profile.phone, email: profile.email })
  const [model, setModel] = useState<ModelSettings | null>(null)
  const [deepseekKey, setDeepseekKey] = useState('')
  const [mineruToken, setMineruToken] = useState('')
  const [testing, setTesting] = useState<'deepseek' | 'mineru' | null>(null)
  const [savingModel, setSavingModel] = useState(false)
  const [pwdOpen, setPwdOpen] = useState(false)
  const [pwdOld, setPwdOld] = useState('')
  const [pwdNew, setPwdNew] = useState('')
  const [pwdConfirm, setPwdConfirm] = useState('')
  const [savingPwd, setSavingPwd] = useState(false)

  useEffect(() => {
    void getModelSettings()
      .then(setModel)
      .catch((err) => showToast(err instanceof Error ? err.message : '加载模型配置失败'))
  }, [showToast])

  const startEdit = () => {
    setDraft({ name: profile.name, gender: profile.gender, phone: profile.phone, email: profile.email })
    setEditing(true)
  }

  const saveEdit = async () => {
    if (!draft.name.trim()) { showToast('昵称不能为空'); return }
    if (draft.phone.trim() && !/^1[0-9]{10}$/.test(draft.phone.trim())) { showToast('请输入正确的 11 位手机号码'); return }
    try {
      await updateProfile({ name: draft.name.trim(), gender: draft.gender, phone: draft.phone.trim() })
      setEditing(false)
      showToast('个人信息已保存')
    } catch (error) { showToast(error instanceof Error ? error.message : '保存失败') }
  }

  const patchDraft = (patch: Partial<typeof draft>) => setDraft((prev) => ({ ...prev, ...patch }))

  const saveModel = async () => {
    setSavingModel(true)
    try {
      await saveModelSettings({
        ...(deepseekKey.trim() ? { deepseek_api_key: deepseekKey.trim() } : {}),
        ...(mineruToken.trim() ? { mineru_token: mineruToken.trim() } : {}),
      })
      const fresh = await getModelSettings()
      setModel(fresh)
      setDeepseekKey('')
      setMineruToken('')
      showToast('模型配置已保存')
    } catch (err) {
      showToast(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSavingModel(false)
    }
  }

  const runTest = async (which: 'deepseek' | 'mineru') => {
    setTesting(which)
    try {
      if (which === 'deepseek') await testDeepSeek()
      else await testMinerU()
      showToast(which === 'deepseek' ? 'DeepSeek 连接正常' : 'MinerU Token 有效')
    } catch (err) {
      showToast(err instanceof Error ? err.message : '测试失败')
    } finally {
      setTesting(null)
    }
  }

  const submitPassword = async () => {
    const passwordError = validateNewPassword(pwdNew)
    if (passwordError) { showToast(passwordError); return }
    if (pwdNew !== pwdConfirm) {
      showToast('两次输入的新密码不一致')
      return
    }
    setSavingPwd(true)
    try {
      await changePasswordCurrent(pwdOld, pwdNew, pwdConfirm)
      showToast('密码已修改，请重新登录')
      setPwdOpen(false)
      setPwdOld(''); setPwdNew(''); setPwdConfirm('')
    } catch (err) {
      showToast(err instanceof Error ? err.message : '修改密码失败')
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
            <span className="text-sm text-ink">{profile.email}（通过账号安全换绑）</span>
          </div>
        </div>
      </div>

      <SecuritySettings />

      {/* 模型配置 */}
      <div className="mb-4 rounded-xl border border-line/70 bg-white p-5 shadow-[0_4px_16px_rgba(30,90,180,0.05)]">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-bold text-ink">
            <span className="h-3.5 w-1 rounded-full bg-primary" />
            模型配置
          </h3>
          <button
            type="button"
            onClick={() => void saveModel()}
            disabled={savingModel}
            className="inline-flex items-center gap-1 rounded-lg bg-primary px-3.5 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#1a5fe6] disabled:opacity-60"
          >
            {savingModel && <Loader2 size={12} className="animate-spin" />}
            保存
          </button>
        </div>

        <div className="space-y-4 px-2">
          <div className="rounded-xl border border-line p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-ink">{model?.deepseek_model ?? 'DeepSeek Flash'}</span>
              <span className={`rounded px-1.5 py-0.5 text-[11px] ${model?.deepseek_key_configured ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}>
                {model?.deepseek_key_configured ? `已配置 ${model.deepseek_key_masked ?? ''}` : '未配置'}
              </span>
            </div>
            <p className="mt-1 text-xs text-ink-3">用于出题、HyDE 查询优化与主观题批卷</p>
            <div className="mt-2.5 flex gap-2">
              <input
                type="password"
                value={deepseekKey}
                onChange={(e) => setDeepseekKey(e.target.value)}
                placeholder="填写新的 DeepSeek API Key，留空表示不修改"
                className={fieldCls}
              />
              <button
                type="button"
                onClick={() => void runTest('deepseek')}
                disabled={testing === 'deepseek'}
                className="shrink-0 rounded-lg border border-line px-3 text-xs text-ink-2 transition-colors hover:border-primary/50 hover:text-primary disabled:opacity-60"
              >
                {testing === 'deepseek' ? '测试中…' : '测试连接'}
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-line p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-ink">MinerU OCR</span>
              <span className={`rounded px-1.5 py-0.5 text-[11px] ${model?.mineru_token_configured ? 'bg-emerald-50 text-emerald-600' : 'bg-page text-ink-3'}`}>
                {model?.mineru_token_configured ? `已配置 ${model.mineru_token_masked ?? ''}` : '使用系统默认 Token'}
              </span>
            </div>
            <p className="mt-1 text-xs text-ink-3">
              扫描件解析，单文件 ≤ {model?.mineru_limits.max_file_mb ?? 200} MB，页数 ≤ {model?.mineru_limits.max_pages ?? 200} 页
            </p>
            <div className="mt-2.5 flex gap-2">
              <input
                type="password"
                value={mineruToken}
                onChange={(e) => setMineruToken(e.target.value)}
                placeholder="填写新的 MinerU Token，留空表示不修改"
                className={fieldCls}
              />
              <button
                type="button"
                onClick={() => void runTest('mineru')}
                disabled={testing === 'mineru'}
                className="shrink-0 rounded-lg border border-line px-3 text-xs text-ink-2 transition-colors hover:border-primary/50 hover:text-primary disabled:opacity-60"
              >
                {testing === 'mineru' ? '测试中…' : '测试连接'}
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-dashed border-line bg-page/60 p-3 text-xs text-ink-3">
            <p>系统内置向量模型：{model?.embedding_model ?? 'BAAI/bge-m3'}（不可配置）</p>
            <p className="mt-1">系统内置重排模型：{model?.rerank_model ?? 'BAAI/bge-reranker-v2-m3'}（不可配置）</p>
          </div>
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
              <p className="mt-0.5 text-xs text-ink-3">修改后需要重新登录</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              setPwdOld('')
              setPwdNew('')
              setPwdConfirm('')
              setPwdOpen(true)
            }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-[0_4px_12px_rgba(30,111,255,0.30)] transition-all hover:bg-[#1a5fe6] active:scale-[0.97]"
          >
            <KeyRound size={14} />
            修改密码
          </button>
        </div>
      </div>

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
