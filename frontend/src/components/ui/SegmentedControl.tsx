import { CHAT_MODE_LABELS } from '../../types'
import type { ChatMode } from '../../types'

const MODES = ['generate', 'creative', 'qa', 'data'] as const satisfies readonly ChatMode[]

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
      className="relative inline-flex rounded-lg bg-page p-0.5 text-xs shadow-[0_1px_4px_rgba(30,90,180,0.10)]"
      role="group"
      aria-label="对话模式"
    >
      <span
        aria-hidden
        className="absolute inset-y-0.5 left-0.5 rounded-md bg-white shadow-[0_1px_5px_rgba(30,90,180,0.16)] transition-transform duration-200 ease-out"
        style={{ width: 'calc((100% - 4px) / 4)', transform: `translateX(${current * 100}%)` }}
      />
      {MODES.map((mode, i) => (
        <button
          key={mode}
          type="button"
          disabled={disabled}
          aria-pressed={i === current}
          onClick={() => onChange(mode)}
          className={`relative z-10 whitespace-nowrap rounded-md px-2.5 py-1 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${
            i === current ? 'text-ink' : 'text-ink-3 hover:text-ink-2'
          }`}
        >
          {CHAT_MODE_LABELS[mode]}
        </button>
      ))}
    </div>
  )
}
