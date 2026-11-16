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
  const { activeTab, setActiveTab, clearAll, generationRecoveryError, resetGenerationRecovery } = useApp()
  const [confirmClear, setConfirmClear] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
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
      {generationRecoveryError && (
        <button type="button" onClick={() => setConfirmReset(true)}
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-500 hover:bg-red-100">
          重置出题恢复记录
        </button>
      )}
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
          message="将取消当前快速出题，并删除预览题目、相关收藏及当前对话。后台完全退出且清理完成后才能再次出题。操作不可恢复，确定继续吗？"
          confirmText="确认清空"
          onConfirm={clearAll}
          onClose={() => setConfirmClear(false)}
        />
      )}
      {confirmReset && (
        <ConfirmDialog
          title="重置出题恢复记录"
          message={`${generationRecoveryError ?? ''}。重置会移除本机无法使用的任务记录，无法据此取消后台任务；后台仍忙碌时会拒绝再次生成。确定重置吗？`}
          confirmText="确认重置"
          onConfirm={resetGenerationRecovery}
          onClose={() => setConfirmReset(false)}
        />
      )}
    </div>
  )
}
