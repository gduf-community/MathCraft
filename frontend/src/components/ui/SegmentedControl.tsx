const TABS = [
  { code: 'generate', label: '快速出题' },
  { code: 'creative', label: '创新命题' },
  { code: 'qa', label: '知识答疑' },
  { code: 'data', label: '数据管理' },
] as const
export type ChatMode = (typeof TABS)[number]['code']
export const MODE_LABEL: Record<ChatMode, string> = Object.fromEntries(
  TABS.map((t) => [t.code, t.label]),
) as Record<ChatMode, string>

/** iOS 风格滑动分段控制器：宽度贴合文字，白色滑块随当前段平移；模式与提示词模板一一对应 */
export default function SegmentedControl({
  value,
  onChange,
}: {
  value: ChatMode
  onChange: (mode: ChatMode) => void
}) {
  const index = TABS.findIndex((t) => t.code === value)
  const current = index < 0 ? 0 : index
  return (
    <div
      className="relative inline-flex rounded-lg bg-page p-0.5 text-xs shadow-[0_1px_4px_rgba(30,90,180,0.10)]"
      role="tablist"
      aria-label="对话模式"
    >
      <span
        aria-hidden
        className="absolute inset-y-0.5 left-0.5 rounded-md bg-white shadow-[0_1px_5px_rgba(30,90,180,0.16)] transition-transform duration-200 ease-out"
        style={{ width: 'calc((100% - 4px) / 4)', transform: `translateX(${current * 100}%)` }}
      />
      {TABS.map((tab, i) => (
        <button
          key={tab.code}
          type="button"
          role="tab"
          aria-selected={i === current}
          onClick={() => onChange(tab.code)}
          className={`relative z-10 whitespace-nowrap rounded-md px-2.5 py-1 font-medium transition-colors ${
            i === current ? 'text-ink' : 'text-ink-3 hover:text-ink-2'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
