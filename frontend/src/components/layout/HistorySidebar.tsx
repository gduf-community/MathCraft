import { useState } from 'react'
import { ChevronsLeft, ChevronsRight, Clock, FileText, MessageCircle } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import type { ChatSessionSummary } from '../../store/AppContext'
import Dropdown from '../ui/Dropdown'
import ConfirmDialog from '../ui/ConfirmDialog'

/** 非可用文档的下拉提示文案 */
const DOC_STATUS_LABELS: Record<string, string> = {
  uploaded: '排队等待解析',
  parsing: '正在解析',
  ocr: 'OCR 识别中',
  chunking: '正在切片',
  embedding: '正在向量化',
  failed: '入库失败',
}

/** 会话列表日期：MM/DD，无效时间显示占位 */
function formatDay(iso: string | null): string {
  if (!iso) return '--/--'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '--/--'
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${month}/${day}`
}

/** 右侧「历史对话」面板：选择题库文档 + 按账号隔离的历史会话，可折叠 */
export default function HistorySidebar() {
  const {
    historyCollapsed,
    toggleHistory,
    kbs,
    docs,
    selectedKbId,
    selectedDocId,
    selectKb,
    selectDoc,
    sessions,
    activeSessionId,
    openSession,
    removeSession,
    botThinking,
  } = useApp()
  const [pendingDelete, setPendingDelete] = useState<ChatSessionSummary | null>(null)

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
        {/* 选择题库文档：先选题库，再选其中一份文档 */}
        <section className="shrink-0">
          <h3 className="mb-2 flex items-center gap-1.5 text-[13px] font-bold text-ink">
            <FileText size={14} className="text-primary" />
            选择题库文档
          </h3>
          <Dropdown
            value={selectedKbId}
            options={kbs.map((k) => ({ value: k.id, label: k.name }))}
            onChange={(v) => selectKb(v)}
            placeholder="未选择"
            searchable
            emptyText="没有匹配的题库"
          />
          <ul className="mt-2 max-h-[168px] space-y-1 overflow-y-auto">
            {docs.map((d) => {
              const selected = d.id === selectedDocId
              const status = d.status
              const ready = status === 'ready' || !status
              const failed = status === 'failed'
              return (
                <li key={d.id}>
                  <button
                    type="button"
                    disabled={!ready}
                    onClick={() => ready && selectDoc(d.id)}
                    className={`flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[13px] transition-colors ${
                      selected
                        ? 'border-primary/50 bg-primary-weak'
                        : ready
                          ? 'border-line bg-white hover:border-primary/40'
                          : 'cursor-not-allowed border-line/60 bg-page/70'
                    }`}
                  >
                    <FileText size={14} className={selected ? 'shrink-0 text-primary' : ready ? 'shrink-0 text-ink-3' : 'shrink-0 text-ink-3/60'} />
                    <span
                      className={`flex-1 truncate ${
                        selected ? 'font-medium text-ink' : ready ? 'text-ink-2' : 'text-ink-3/70'
                      }`}
                    >
                      {d.name}
                    </span>
                    {!ready && (
                      <span className={`shrink-0 text-[11px] ${failed ? 'text-red-400' : 'text-primary/70'}`}>
                        {failed ? '入库失败' : `${DOC_STATUS_LABELS[status] ?? '处理中'} ${d.progress ?? 0}%`}
                      </span>
                    )}
                  </button>
                </li>
              )
            })}
            {!docs.length && <li className="py-2 text-center text-[11px] text-ink-3">该题库暂无文档，可在题库管理中上传</li>}
          </ul>
        </section>

        {/* 历史会话列表：按账号隔离，点击继续对话，右键删除单条 */}
        <section className="mt-3 flex min-h-0 flex-1 flex-col">
          <h3 className="mb-2 flex shrink-0 items-center gap-1.5 text-[13px] font-bold text-ink">
            <MessageCircle size={14} className="text-primary" />
            会话记录
          </h3>
          <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-0.5" aria-label="历史会话列表">
            {sessions.map((session) => {
              const active = session.id === activeSessionId
              return (
                <li key={session.id}>
                  <button
                    type="button"
                    disabled={botThinking}
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
                    <MessageCircle size={14} className={`shrink-0 ${active ? 'text-primary' : 'text-ink-3'}`} />
                    <span className={`min-w-0 flex-1 truncate ${active ? 'font-medium' : ''}`}>
                      {session.title}
                    </span>
                    <span className={`shrink-0 text-[11px] tabular-nums ${active ? 'text-primary/80' : 'text-ink-3'}`}>
                      {formatDay(session.lastMessageAt)}
                    </span>
                  </button>
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
