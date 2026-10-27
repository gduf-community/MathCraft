import { useState } from 'react'
import { Clock, FileText, Folder, Pencil, Star, Tag, Trash2, Users } from 'lucide-react'
import { TYPE_LABELS } from '../../../constants'
import { Latex } from '../../../lib/latex'
import { formatCollectedAt } from '../../../lib/relativeTime'
import type { Difficulty } from '../../../types'
import type { FavoriteItem } from '../../../types/favorites'
import AnswerPanel from '../PreviewTab/AnswerPanel'

const DIFFICULTY_COLOR: Record<Difficulty, string> = {
  低: '#16a34a',
  中: '#f59e0b',
  高: '#f97316',
  地狱: '#ef4444',
}

interface Props {
  item: FavoriteItem
  folderName: string
  selected: boolean
  compact: boolean
  onToggleSelect: () => void
  onRemove: () => void
  onAssemble: () => void
  onEdit: () => void
}

/** B-1..B-8：收藏页只读题目卡片 */
export default function FavoriteCard({
  item,
  folderName,
  selected,
  compact,
  onToggleSelect,
  onRemove,
  onAssemble,
  onEdit,
}: Props) {
  const [expanded, setExpanded] = useState(false)
  const q = item.question

  return (
    <article
      className={`grid grid-cols-[24px_minmax(0,1fr)] gap-3 rounded-xl border bg-white transition-shadow hover:shadow-[0_4px_16px_rgba(30,90,180,0.08)] ${
        compact ? 'p-3' : 'p-3.5'
      } ${
        selected
          ? 'border-primary/60 shadow-[0_0_0_1px_rgba(30,111,255,0.25),0_4px_16px_rgba(30,90,180,0.08)]'
          : 'border-line'
      }`}
    >
      <div className="flex flex-col items-center gap-2 pt-0.5">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelect}
          aria-label="选择本题"
          className="h-4 w-4 accent-primary"
        />
        <button
          type="button"
          title="取消收藏"
          aria-label="取消收藏"
          aria-pressed
          onClick={onRemove}
          className="grid h-6 w-6 place-items-center rounded-full text-star transition-transform hover:scale-110 hover:bg-[rgba(255,179,0,0.14)]"
        >
          <Star size={16} fill="currentColor" />
        </button>
      </div>

      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2.5 text-xs">
          <span className="rounded bg-primary-light px-1.5 py-0.5 font-medium text-primary">
            {TYPE_LABELS[q.type]}
          </span>
          <span className="inline-flex items-center gap-1.5 text-ink-2">
            <i
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: DIFFICULTY_COLOR[q.difficulty] }}
            />
            难度：{q.difficulty}
          </span>
          {q.knowledgePoint && (
            <span className="inline-flex items-center gap-1 rounded-full border border-line/90 bg-[#f4f7fc] px-2 py-0.5 text-ink-2">
              <Tag size={12} className="text-ink-3" />
              {q.knowledgePoint}
            </span>
          )}
          {!compact && <span className="text-ink-3">{q.id}</span>}
        </div>

        <p
          className={`font-medium text-ink ${compact ? 'mt-1.5 line-clamp-1 text-[15px] leading-6' : 'mt-2 text-[16px] leading-7'}`}
        >
          <Latex text={q.stem} />
        </p>

        {!compact && q.options.length > 0 && (
          <div className="mt-2.5 flex flex-wrap gap-x-8 gap-y-2">
            {q.options.map((option) => (
              <div key={option.label} className="flex items-baseline gap-1.5 text-sm text-ink-2">
                <span className="font-medium text-ink-3">{option.label}.</span>
                <Latex text={option.text} />
              </div>
            ))}
          </div>
        )}

        {!compact && (
          <div className="mt-2.5">
            <AnswerPanel q={q} editing={false} expanded={expanded} onToggle={() => setExpanded((value) => !value)} />
          </div>
        )}

        <div className="mt-2.5 flex flex-wrap items-center gap-2 border-t border-dashed border-line/80 pt-2.5">
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
            <span className="inline-flex items-center gap-1">
              <Folder size={13} />
              {folderName}
            </span>
            <span className="text-[#d5dbe6]">·</span>
            <span className="inline-flex items-center gap-1">
              <FileText size={13} />
              {item.source.bankName ?? '未知题库'}
              {item.source.chapter ? ` · ${item.source.chapter}` : ''}
            </span>
            <span className="text-[#d5dbe6]">·</span>
            <span className="inline-flex items-center gap-1">
              <Clock size={13} />
              {formatCollectedAt(item.collectedAt)}收藏
            </span>
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onAssemble}
              className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary-light/60 px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary-light"
            >
              <Users size={13} />
              组卷
            </button>
            <button
              type="button"
              onClick={onEdit}
              className="inline-flex items-center gap-1 rounded-md border border-line bg-white px-2.5 py-1 text-xs font-medium text-ink-2 transition-colors hover:border-primary/50 hover:bg-primary-weak hover:text-primary"
            >
              <Pencil size={13} />
              编辑
            </button>
            <button
              type="button"
              onClick={onRemove}
              className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-[#fef2f2] px-2.5 py-1 text-xs font-medium text-danger transition-colors hover:bg-[#fee2e2]"
            >
              <Trash2 size={13} />
              移出收藏
            </button>
          </div>
        </div>
      </div>
    </article>
  )
}
