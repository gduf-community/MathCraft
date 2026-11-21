import { useId, useState } from 'react'
import { ChevronsLeft, ChevronsRight, Clock, MessageCircle } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import type { ChatSessionSummary } from '../../store/AppContext'
import { CHAT_MODE_LABELS } from '../../types'
import ConfirmDialog from '../ui/ConfirmDialog'
import { ChatModeIcon } from '../ui/SegmentedControl'

/** 会话列表日期：MM/DD，无效时间显示占位 */
function formatDay(iso: string | null): string {
  if (!iso) return '--/--'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '--/--'
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${month}/${day}`
}

/** 右侧可折叠的历史对话面板 */
export default function HistorySidebar() {
  const {
    historyCollapsed,
    toggleHistory,
    sessions,
    activeSessionId,
    openSession,
    removeSession,
    botThinking,
  } = useApp()
  const [pendingDelete, setPendingDelete] = useState<ChatSessionSummary | null>(null)
  const modeDescriptionId = useId()

  // 折叠态：右侧细条，点击展开
  if (historyCollapsed) {
    return (
      <aside className="z-10 my-4 mr-4 flex w-12 shrink-0 flex-col items-center gap-3 rounded-2xl border border-line/70 bg-white py-4 shadow-[0_6px_24px_rgba(30,90,180,0.06)]">
        <button
          type="button"
          onClick={toggleHistory}
          title="展开历史对话面板"
          aria-label="展开历史对话面板"
          className="rounded-lg p-1.5 text-ink-3 transition-colors hover:bg-primary-weak hover:text-primary"
        >
          <ChevronsLeft size={18} />
        </button>
        <button
          type="button"
          onClick={toggleHistory}
          className="flex-1 cursor-pointer text-sm font-semibold tracking-[0.3em] text-ink-2 [writing-mode:vertical-rl] transition-colors hover:text-primary"
        >
          历史对话
        </button>
      </aside>
    )
  }

  return (
    <aside className="z-10 my-4 mr-4 flex w-[264px] shrink-0 flex-col overflow-hidden rounded-2xl border border-line/70 bg-white shadow-[0_6px_24px_rgba(30,90,180,0.06)]">
      {/* 面板头部：标题 + 折叠按钮 */}
      <div className="flex items-center justify-between border-b border-line px-4 py-3.5">
        <div className="flex items-center gap-2 text-[16px] font-bold text-ink">
          <Clock size={17} className="text-primary" />
          历史对话
        </div>
        <button
          type="button"
          onClick={toggleHistory}
          title="折叠面板"
          aria-label="折叠历史对话面板"
          className="rounded-lg p-1.5 text-ink-3 transition-colors hover:bg-primary-weak hover:text-primary"
        >
          <ChevronsRight size={15} />
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col px-3.5 pb-3.5 pt-3">
        {/* 历史会话列表：按账号隔离，点击继续对话，右键删除单条 */}
        <section className="flex min-h-0 flex-1 flex-col">
          <h3 className="mb-2 flex shrink-0 items-center gap-1.5 text-[13px] font-bold text-ink">
            <MessageCircle size={14} className="text-primary" />
            会话记录
          </h3>
          <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-0.5" aria-label="历史会话列表">
            {sessions.map((session) => {
              const active = session.id === activeSessionId
              const mode = session.mode ?? 'generate'
              const descriptionId = `${modeDescriptionId}-${session.id}`
              return (
                <li key={session.id}>
                  <button
                    type="button"
                    disabled={botThinking}
                    aria-current={active ? 'true' : undefined}
                    aria-describedby={descriptionId}
                    onClick={() => void openSession(session)}
                    onContextMenu={(e) => {
                      e.preventDefault()
                      if (!botThinking) setPendingDelete(session)
                    }}
                    title={`${session.title}（右键删除）`}
                    className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors ${
                      active
                        ? 'bg-primary-weak text-primary'
                        : 'text-ink-2 hover:bg-page hover:text-ink'
                    } disabled:cursor-not-allowed disabled:opacity-50`}
                  >
                    <ChatModeIcon mode={mode} className={`shrink-0 ${active ? 'text-primary' : 'text-ink-3'}`} />
                    <span className={`min-w-0 flex-1 truncate ${active ? 'font-medium' : ''}`}>
                      {session.title}
                    </span>
                    <span className={`shrink-0 text-[11px] tabular-nums ${active ? 'text-primary/80' : 'text-ink-3'}`}>
                      {formatDay(session.lastMessageAt)}
                    </span>
                  </button>
                  <span id={descriptionId} hidden>{CHAT_MODE_LABELS[mode]}</span>
                </li>
              )
            })}
            {!sessions.length && (
              <li className="rounded-lg border border-dashed border-line/80 px-3 py-6 text-center text-xs text-ink-3">
                暂无历史对话，发送第一条消息后自动保存
              </li>
            )}
          </ul>
        </section>
      </div>

      {pendingDelete && (
        <ConfirmDialog
          title="删除对话"
          message={`将删除「${pendingDelete.title}」的对话记录，操作不可恢复。确定继续吗？`}
          confirmText="确认删除"
          onConfirm={() => removeSession(pendingDelete.id)}
          onClose={() => setPendingDelete(null)}
        />
      )}
    </aside>
  )
}
