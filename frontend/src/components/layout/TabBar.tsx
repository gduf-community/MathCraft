import { useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import { FileText, MessagesSquare, Trash2 } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import type { TabKey } from '../../store/AppContext'
import ConfirmDialog from '../ui/ConfirmDialog'

const TABS: { key: TabKey; label: string; icon: LucideIcon }[] = [
  { key: 'generate', label: 'Agent出题', icon: MessagesSquare },
  { key: 'preview', label: '题目预览', icon: FileText },
]

export default function TabBar() {
  const { activeTab, setActiveTab, clearAll } = useApp()
  const [confirmClear, setConfirmClear] = useState(false)
  return (
    <div className="workspace-tabs flex shrink-0 items-center gap-6 border-b border-line px-6">
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
      <button
        type="button"
        onClick={() => setConfirmClear(true)}
        className="ml-auto flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-500 transition-colors hover:bg-red-100"
      >
        <Trash2 size={13} />
        一键清空
      </button>
      {confirmClear && (
        <ConfirmDialog
          title="一键清空"
          message="将清空「题目预览」中的全部题目、AI 对话记录以及当前对话记忆（出题进度），操作不可恢复。确定继续吗？"
          confirmText="确认清空"
          onConfirm={clearAll}
          onClose={() => setConfirmClear(false)}
        />
      )}
    </div>
  )
}
