import type { LucideIcon } from 'lucide-react'
import { FileText, MessagesSquare } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import type { TabKey } from '../../store/AppContext'

const TABS: { key: TabKey; label: string; icon: LucideIcon }[] = [
  { key: 'generate', label: '智能生成', icon: MessagesSquare },
  { key: 'preview', label: '题目预览', icon: FileText },
]

export default function TabBar() {
  const { activeTab, setActiveTab } = useApp()
  return (
    <div className="flex shrink-0 items-center gap-6 border-b border-line px-6">
      {TABS.map(({ key, label, icon: Icon }) => {
        const active = activeTab === key
        return (
          <button
            key={key}
            type="button"
            onClick={() => setActiveTab(key)}
            className={`relative flex items-center gap-1.5 py-3.5 text-[16px] transition-colors ${
              active ? 'font-semibold text-primary' : 'text-ink-2 hover:text-primary'
            }`}
          >
            <Icon size={17} />
            {label}
            {active && <span className="absolute inset-x-1 bottom-0 h-[3px] rounded-t-full bg-primary" />}
          </button>
        )
      })}
    </div>
  )
}
