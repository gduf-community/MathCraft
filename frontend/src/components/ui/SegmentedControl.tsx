import { Database, MessageCircleQuestion, Sparkles, Zap } from 'lucide-react'
import { CHAT_MODE_LABELS } from '../../types'
import type { ChatMode } from '../../types'

const MODES = ['generate', 'creative', 'qa', 'data'] as const satisfies readonly ChatMode[]
const MODE_ICONS = {
  generate: Zap,
  creative: Sparkles,
  qa: MessageCircleQuestion,
  data: Database,
}

export function ChatModeIcon({ mode, className }: { mode: ChatMode; className?: string }) {
  const Icon = MODE_ICONS[mode] ?? MODE_ICONS.generate
  return <Icon size={14} aria-hidden="true" className={className} />
}

/** iOS 风格滑动分段控制器：宽度贴合文字，白色滑块随当前段平移；模式与提示词模板一一对应 */
export default function SegmentedControl({
  value,
  onChange,
  disabled = false,
}: {
  value: ChatMode
  onChange: (mode: ChatMode) => void
  disabled?: boolean
}) {
  const index = MODES.findIndex((mode) => mode === value)
  const current = index < 0 ? 0 : index
  return (
    <div
      className="relative grid w-fit max-w-full grid-cols-4 rounded-lg bg-page p-0.5 text-xs shadow-[0_1px_4px_rgba(30,90,180,0.10)]"
      role="group"
      aria-label="对话模式"
    >
      <span
        aria-hidden
        className="absolute inset-y-0.5 left-0.5 rounded-md bg-white shadow-[0_1px_5px_rgba(30,90,180,0.16)] motion-safe:transition-transform motion-safe:duration-200 motion-safe:ease-out"
        style={{ width: 'calc((100% - 4px) / 4)', transform: `translateX(${current * 100}%)` }}
      />
      {MODES.map((mode, i) => (
        <button
          key={mode}
          type="button"
          disabled={disabled}
          aria-pressed={i === current}
          onClick={() => onChange(mode)}
          className={`relative z-10 flex min-w-0 items-center justify-center gap-1 rounded-md px-1 py-1 font-medium transition-colors focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-45 sm:px-2.5 ${
            i === current ? 'text-ink' : 'text-ink-3 hover:text-ink-2'
          }`}
        >
          <ChatModeIcon mode={mode} className="shrink-0" />
          <span className="min-w-0 truncate">{CHAT_MODE_LABELS[mode]}</span>
        </button>
      ))}
    </div>
  )
}
