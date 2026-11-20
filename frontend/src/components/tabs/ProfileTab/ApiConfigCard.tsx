/** 个人中心 API 配置卡：DeepSeek 与 OCR-MinerU Key 的保存与连接测试。
 * Key 保存到服务端账户（供后端调用），同时完整值保存在本机浏览器（localStorage，按用户隔离），
 * 供眼睛图标在本机回显；服务端接口只返回掩码，不回传完整凭据。 */
import { Eraser, HelpCircle, Info, Loader2, Save } from 'lucide-react'
import { Eye, EyeOff } from 'lucide-react'
import { useRef, useState } from 'react'
import { saveModelSettings, testDeepSeek, testMinerU } from '../../../api/backend'
import { useAuth } from '../../../store/AuthContext'
import { useApp } from '../../../store/AppContext'

type Service = 'deepseek' | 'mineru'
type Busy = `${Service}-save` | `${Service}-test` | null

const KEY_STORE = 'mathcraft-personal-keys'

function readStoredKey(userId: string, service: Service): string {
  try {
    const raw = localStorage.getItem(KEY_STORE)
    if (!raw) return ''
    const store = JSON.parse(raw) as Record<string, Partial<Record<Service, string>>>
    return store[userId]?.[service] ?? ''
  } catch {
    return ''
  }
}

function writeStoredKey(userId: string, service: Service, value: string) {
  try {
    const raw = localStorage.getItem(KEY_STORE)
    const store = raw ? JSON.parse(raw) as Record<string, Partial<Record<Service, string>>> : {}
    localStorage.setItem(KEY_STORE, JSON.stringify({
      ...store,
      [userId]: { ...store[userId], [service]: value },
    }))
  } catch {
    /* 存储被禁用时跳过本机回显，不影响保存 */
  }
}

interface ApiKeyRowProps {
  label: string
  placeholder: string
  hint: string
  service: Service
  configured: boolean
  masked: string | null
  saving: boolean
  testing: boolean
  onSave: (value: string) => Promise<void>
  onTest: (value?: string) => Promise<void>
}

function ApiKeyRow({ label, placeholder, hint, service, configured, masked, saving, testing, onSave, onTest }: ApiKeyRowProps) {
  const { user } = useAuth()
  const { showToast } = useApp()
  const userId = user?.userId ?? ''
  const inputRef = useRef<HTMLInputElement>(null)
  // 本机保存的完整 Key；在其他设备配置的 Key 只能显示服务端掩码
  const [fullKey, setFullKey] = useState(() => readStoredKey(userId, service))
  const [draft, setDraft] = useState('')
  // browse：展示掩码/完整 Key；edit：填写草稿。仅保存成功回到 browse，清空后保持 edit 避免回填
  const [mode, setMode] = useState<'browse' | 'edit'>('browse')
  const [reveal, setReveal] = useState(false)
  const busy = saving || testing
  const trimmed = draft.trim()
  const dirty = trimmed !== ''
  // browse：明文展示打码掩码（sk-****abcd），眼睛切换为本机完整 Key；edit：显示草稿
  const display = dirty
    ? draft
    : mode === 'edit' ? '' : reveal && fullKey ? fullKey : configured ? masked ?? '' : ''

  const save = () => {
    if (busy || !dirty) return
    void onSave(trimmed).then(() => {
      writeStoredKey(userId, service, trimmed)
      setFullKey(trimmed)
      setDraft('')
      setMode('browse')
      setReveal(false)
    })
  }

  const clear = () => {
    if (busy) return
    setDraft('')
    setMode('edit')
    setReveal(false)
    inputRef.current?.focus()
  }

  const toggleReveal = () => {
    if (dirty) { setReveal((v) => !v); return }
    if (!fullKey) {
      showToast('完整 Key 仅保存在配置它的这台电脑上；本机没有记录，请重新输入 Key 并保存一次', 'error')
      return
    }
    if (mode === 'edit') {
      // 编辑态草稿为空时点眼睛 = 填入本机保存的完整 Key，便于查看或覆盖
      setDraft(fullKey)
      setReveal(true)
      return
    }
    setReveal((v) => !v)
  }

  const showEye = mode === 'edit' || configured
  const eyeTitle = dirty
    ? (reveal ? '隐藏输入内容' : '显示输入内容')
    : mode === 'edit' && fullKey
      ? '填入本机保存的完整 Key'
      : reveal ? '显示掩码' : '显示完整 Key'

  return (
    <div>
      <div className="flex items-center gap-3">
        <label className="flex w-40 shrink-0 items-center gap-1 whitespace-nowrap text-sm font-medium text-ink">
          {label}
          <HelpCircle size={13} className="shrink-0 text-ink-3" />
        </label>
        <div className="relative min-w-0 flex-1">
          <input
            ref={inputRef}
            type={dirty ? (reveal ? 'text' : 'password') : 'text'}
            value={display}
            autoComplete="new-password"
            aria-label={placeholder}
            placeholder={placeholder}
            onFocus={() => {
              // 浏览态点击输入框即进入编辑并清空草稿，避免掩码展示值混入输入被误保存
              if (mode === 'browse' && !dirty) {
                setMode('edit')
                setDraft('')
                setReveal(false)
              }
            }}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.nativeEvent.isComposing) save()
            }}
            className="block w-full rounded-lg border border-line bg-white py-2 pl-3 pr-9 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary disabled:opacity-60"
            disabled={busy}
          />
          {showEye && (
            <button
              type="button"
              title={eyeTitle}
              aria-label={eyeTitle}
              onClick={toggleReveal}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-ink-3 transition-colors hover:text-primary"
            >
              {reveal ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={() => void onTest(dirty ? trimmed : undefined)}
          disabled={busy || (!configured && !dirty)}
          title={!configured && !dirty ? '请先输入或保存 Key' : dirty ? '测试当前输入的 Key（不保存）' : '测试已保存的配置'}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-primary/40 bg-white px-3.5 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary-light/60 disabled:cursor-not-allowed disabled:opacity-45"
        >
          {testing && <Loader2 size={13} className="animate-spin" />}
          测试
        </button>
        <button
          type="button"
          onClick={clear}
          disabled={busy}
          title="清空输入，重新填写"
          aria-label={`清空${label}输入`}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-line bg-white px-3.5 py-2 text-sm text-ink-2 transition-colors hover:border-primary/50 hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
        >
          <Eraser size={13} />
          清空
        </button>
        <button
          type="button"
          onClick={save}
          disabled={busy || !dirty}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-primary px-3.5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#1a5fe6] disabled:cursor-not-allowed disabled:opacity-45"
        >
          {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          保存
        </button>
      </div>
      <p className="mb-1 mt-1.5 pl-[172px] text-xs text-ink-3">{hint}</p>
    </div>
  )
}

/** API 配置卡：输入框缩短，右侧同行放置测试与保存按钮 */
export function ApiConfigCard() {
  const { modelSettings, refreshModelSettings, showToast } = useApp()
  const [busy, setBusy] = useState<Busy>(null)

  const save = async (service: Service, value: string) => {
    if (busy) return
    setBusy(`${service}-save`)
    try {
      await saveModelSettings(service === 'deepseek' ? { deepseek_api_key: value } : { mineru_token: value })
      await refreshModelSettings()
      showToast(service === 'deepseek' ? '校内 DeepSeek Key 已保存' : 'OCR-MinerU Key 已保存', 'success')
    } catch (error) {
      showToast(error instanceof Error ? error.message : '保存失败，请重试', 'error')
    } finally {
      setBusy(null)
    }
  }

  const test = async (service: Service, value?: string) => {
    if (busy) return
    setBusy(`${service}-test`)
    try {
      if (service === 'deepseek') await testDeepSeek(value)
      else await testMinerU(value)
      showToast(service === 'deepseek'
        ? '校内 DeepSeek 连接成功'
        : 'OCR-MinerU 连接成功，实际解析仍受额度与任务影响', 'success')
    } catch (error) {
      showToast(error instanceof Error ? error.message : '连接失败，请检查 Key 或服务可用性', 'error')
    } finally {
      setBusy(null)
    }
  }

  const loading = modelSettings === null

  return (
    <div className="mb-4 rounded-xl border border-line/70 bg-white p-5 shadow-[0_4px_16px_rgba(30,90,180,0.05)]">
      <h3 className="mb-5 flex items-center gap-2 text-sm font-bold text-ink">
        <span className="h-3.5 w-1 rounded-full bg-primary" />
        API 配置
      </h3>
      {loading ? (
        <p role="status" className="flex items-center gap-2 py-4 text-sm text-ink-2">
          <Loader2 size={14} className="animate-spin" />
          正在读取配置…
        </p>
      ) : (
        <div className="space-y-5">
          <ApiKeyRow
            label="校内 DeepSeek Key"
            service="deepseek"
            placeholder="请输入您的校内 DeepSeek Key"
            hint="用于调用校内部署的 DeepSeek 服务（newapi.ai.gduf.top），请妥善保管您的 Key"
            configured={modelSettings.deepseek_key_configured}
            masked={modelSettings.deepseek_key_masked}
            saving={busy === 'deepseek-save'}
            testing={busy === 'deepseek-test'}
            onSave={(value) => save('deepseek', value)}
            onTest={(value) => test('deepseek', value)}
          />
          <ApiKeyRow
            label="OCR-MinerU Key"
            service="mineru"
            placeholder="请输入您的 OCR-MinerU Key"
            hint="用于 OCR-MinerU 的 OCR 识别功能，请妥善保管您的 Key"
            configured={modelSettings.mineru_token_configured}
            masked={modelSettings.mineru_token_masked}
            saving={busy === 'mineru-save'}
            testing={busy === 'mineru-test'}
            onSave={(value) => save('mineru', value)}
            onTest={(value) => test('mineru', value)}
          />
        </div>
      )}
      <div className="mt-5 flex items-start gap-2 rounded-lg bg-primary-light/60 px-3 py-2.5">
        <Info size={15} className="mt-0.5 shrink-0 text-primary" />
        <p className="text-xs leading-5 text-ink-2">
          上述 Key 将保存到您的账户，完整 Key 同时保存在本机浏览器中；在其他电脑配置的 Key 在本机只能显示打码样式。
        </p>
      </div>
    </div>
  )
}
