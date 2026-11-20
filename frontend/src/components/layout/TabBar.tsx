import { useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import { FileText, MessagesSquare, Plus, Trash2 } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import type { TabKey } from '../../store/AppContext'
import ConfirmDialog from '../ui/ConfirmDialog'

const TABS: { key: TabKey; label: string; icon: LucideIcon }[] = [
  { key: 'generate', label: 'Agent出题', icon: MessagesSquare },
  { key: 'preview', label: '题目预览', icon: FileText },
]

export default function TabBar() {
  const {
    activeTab, setActiveTab, startNewChat, clearQuestions, botThinking, chatPauseStatus, sessionLoading,
    confirmBusy, pendingConfirm, generating, generationClearing, questionsClearing,
    generationRecoveryError, resetGenerationRecovery, retryGenerationCleanup,
  } = useApp()
  const clearDisabled = botThinking || chatPauseStatus != null || sessionLoading || confirmBusy || pendingConfirm !== null
    || generating || generationClearing || questionsClearing || generationRecoveryError !== null
  const [confirmClear, setConfirmClear] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [confirmRecovery, setConfirmRecovery] = useState(false)
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
      {generationClearing && !generationRecoveryError && (
        <button type="button" onClick={() => setConfirmRecovery(true)}
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-500 hover:bg-red-100">
          继续清理历史任务
        </button>
      )}
      {activeTab === 'generate' ? (
        <button
          type="button"
          onClick={startNewChat}
          title="开始一次新的对话，当前对话保留在历史记录中"
          className="ml-auto flex items-center gap-1.5 rounded-lg border border-primary/35 bg-primary-weak px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:border-primary hover:bg-primary hover:text-white"
        >
          <Plus size={13} />
          新建对话
        </button>
      ) : (
        <button
          type="button"
          disabled={clearDisabled}
          onClick={() => setConfirmClear(true)}
          title="清空题目预览中的全部题目，对话记录不受影响"
          className="ml-auto flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-500 transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-45"
        >
          <Trash2 size={13} />
          一键清空
        </button>
      )}
      {confirmClear && (
        <ConfirmDialog
          title="一键清空"
          message="将清空「题目预览」中的全部题目，对话记录与其他数据不受影响，操作不可恢复。确定继续吗？"
          confirmText="确认清空"
          onConfirm={clearQuestions}
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
      {confirmRecovery && (
        <ConfirmDialog
          title="继续清理历史任务"
          message="继续此前已保存的任务清理：等待原任务退出，删除该任务待清理的题目及历史会话。失败后保留进度，可再次重试。"
          confirmText="继续清理"
          onConfirm={retryGenerationCleanup}
          onClose={() => setConfirmRecovery(false)}
        />
      )}
    </div>
  )
}
