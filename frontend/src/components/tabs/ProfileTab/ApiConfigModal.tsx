/** 未配置 API Key 时的引导弹窗：DeepSeek 与 OCR-MinerU 都需配置，可跳转个人中心。 */
import { AlertCircle, ArrowRight, KeyRound, X } from 'lucide-react'
import { useApp } from '../../../store/AppContext'

export default function ApiConfigModal() {
  const { apiConfigOpen, closeApiConfigModal, setActiveTab, modelSettings } = useApp()
  if (!apiConfigOpen) return null
  const missing = [
    !modelSettings?.deepseek_key_configured && '校内 DeepSeek Key（出题、对话必需）',
    !modelSettings?.mineru_token_configured && 'OCR-MinerU Key（扫描件解析、创建题库必需）',
  ].filter(Boolean) as string[]
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4"
      onClick={closeApiConfigModal}
    >
      <div
        className="w-[440px] animate-pop overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="alertdialog"
        aria-label="API 配置提醒"
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h3 className="flex items-center gap-2 text-base font-bold text-ink">
            <KeyRound size={17} className="text-primary" />
            需要配置 API Key
          </h3>
          <button
            type="button"
            onClick={closeApiConfigModal}
            aria-label="关闭"
            className="rounded p-1 text-ink-3 hover:bg-page"
          >
            <X size={18} />
          </button>
        </div>
        <div className="space-y-3 px-5 py-4">
          <p className="flex items-start gap-2 text-sm leading-6 text-ink-2">
            <AlertCircle size={15} className="mt-1 shrink-0 text-amber-500" />
            首次使用请先在「个人中心 → API 配置」中保存以下两项凭据：
          </p>
          <ul className="list-inside list-disc space-y-1 pl-1 text-sm text-ink">
            {missing.map((item) => <li key={item}>{item}</li>)}
          </ul>
          <p className="text-xs text-ink-3">
            未配置校内 DeepSeek Key 时智能出题无法发送；未配置 OCR-MinerU Key 时无法上传扫描件创建题库。
          </p>
        </div>
        <div className="flex justify-end gap-2.5 border-t border-line px-5 py-3.5">
          <button
            type="button"
            onClick={closeApiConfigModal}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 hover:bg-page"
          >
            稍后再说
          </button>
          <button
            type="button"
            onClick={() => {
              closeApiConfigModal()
              setActiveTab('me')
            }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#1a5fe6]"
          >
            去配置
            <ArrowRight size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}
