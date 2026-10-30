import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Clock, FileText, Folder, Tag, X } from 'lucide-react'
import { TYPE_LABELS } from '../../../constants'
import { Latex } from '../../../lib/latex'
import { formatCollectedAt } from '../../../lib/relativeTime'
import type { FavoriteItem } from '../../../types/favorites'
import AnswerPanel from '../PreviewTab/AnswerPanel'

interface Props {
  item: FavoriteItem
  folderName: string
  onClose: () => void
}

/** 收藏题详情弹窗：只读展示完整题干、选项、答案与来源信息 */
export default function QuestionDetailModal({ item, folderName, onClose }: Props) {
  const q = item.question
  const [expanded, setExpanded] = useState(true)
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeRef.current?.focus()
  }, [])

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const trapFocus = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Tab') return
    const root = dialogRef.current
    if (!root) return
    const focusables = [
      ...root.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      ),
    ].filter((element) => !element.hasAttribute('disabled') && element.offsetParent !== null)
    if (!focusables.length) return
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const sourceText = [item.source.bankName ?? '未知题库', item.source.chapter].filter(Boolean).join(' · ')

  return (
    <div
      className="fixed inset-0 z-40 flex animate-fade-in items-center justify-center bg-[#0f1b33]/30 p-6"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="question-detail-title"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={trapFocus}
        className="flex max-h-[85vh] w-full max-w-3xl animate-pop flex-col rounded-2xl bg-white shadow-2xl"
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="rounded bg-primary-light px-2 py-0.5 text-sm font-medium text-primary">
              {TYPE_LABELS[q.type]}
            </span>
            {q.knowledgePoint && (
              <span className="inline-flex items-center gap-1 rounded-full border border-line/90 bg-[#f4f7fc] px-2.5 py-0.5 text-sm text-ink-2">
                <Tag size={13} className="text-ink-3" />
                {q.knowledgePoint}
              </span>
            )}
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="关闭"
            title="关闭"
            className="rounded-lg p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink"
          >
            <X size={18} />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <h2 id="question-detail-title" className="text-[17px] font-bold text-ink">
            题目详情
          </h2>
          <div className="h-4" />

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-ink-3">
            <span>题型：{TYPE_LABELS[q.type]}</span>
            <span>难度：{q.difficulty}</span>
            <span>知识点：{q.knowledgePoint || '未设置'}</span>
            <span>编号：{q.id}</span>
          </div>

          <p className="mt-4 text-[16px] font-medium leading-7 text-ink">
            <Latex text={q.stem} />
          </p>

          {q.options.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-x-8 gap-y-2">
              {q.options.map((option) => (
                <div key={option.label} className="flex items-baseline gap-1.5 text-sm text-ink-2">
                  <span className="font-medium text-ink-3">{option.label}.</span>
                  <Latex text={option.text} />
                </div>
              ))}
            </div>
          )}

          <div className="mt-5">
            <AnswerPanel q={q} editing={false} expanded={expanded} onToggle={() => setExpanded((value) => !value)} />
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-1.5 border-t border-dashed border-line/80 pt-3 text-xs text-ink-3">
            <span className="inline-flex items-center gap-1">
              <Folder size={13} />
              {folderName}
            </span>
            <span className="text-[#d5dbe6]">·</span>
            <span className="inline-flex items-center gap-1" title={sourceText}>
              <FileText size={13} />
              {sourceText}
            </span>
            <span className="text-[#d5dbe6]">·</span>
            <span className="inline-flex items-center gap-1">
              <Clock size={13} />
              {formatCollectedAt(item.collectedAt)}收藏
            </span>
          </div>
        </div>

        <div className="flex shrink-0 justify-end border-t border-line px-6 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:border-ink-3 hover:text-ink"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}
