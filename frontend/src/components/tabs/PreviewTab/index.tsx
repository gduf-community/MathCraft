import { useMemo, useState } from 'react'
import { Bot, ListFilter, Users } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { DIFFICULTIES, TYPE_LABELS, TYPE_ORDER } from '../../../constants'
import type { Difficulty } from '../../../types'
import QuestionCard from './QuestionCard'
import AssembleModal from './AssembleModal'
import Dropdown from '../../ui/Dropdown'

/** 题目预览标签页：题型筛选、难度筛选、题目列表（滚轮滚动，无翻页） */
export default function PreviewTab() {
  const {
    questions,
    selectedIds,
    selectAll,
    clearSelection,
    typeFilter,
    setTypeFilter,
    diffFilter,
    setDiffFilter,
  } = useApp()
  const [assembling, setAssembling] = useState(false)

  const counts = useMemo(() => {
    const map: Record<string, number> = { all: questions.length }
    for (const q of questions) map[q.type] = (map[q.type] ?? 0) + 1
    return map
  }, [questions])

  const filtered = useMemo(
    () =>
      questions.filter(
        (q) =>
          (typeFilter === 'all' || q.type === typeFilter) && (diffFilter === 'all' || q.difficulty === diffFilter),
      ),
    [questions, typeFilter, diffFilter],
  )

  if (!questions.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-ink-3">
        <span className="flex h-16 w-16 items-center justify-center rounded-full bg-primary-light text-primary">
          <Bot size={30} />
        </span>
        <p className="text-sm">暂无题目</p>
        <p className="text-xs">请先在「智能生成」标签页选择题型并生成题目</p>
      </div>
    )
  }

  const visibleIds = filtered.map((q) => q.id)
  const allSelected = filtered.length > 0 && filtered.every((q) => selectedIds.includes(q.id))

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 题型筛选胶囊 */}
      <div className="flex flex-wrap items-center gap-2.5 px-6 pb-3 pt-4">
        <Pill label={`全部 (${counts.all ?? 0})`} active={typeFilter === 'all'} onClick={() => setTypeFilter('all')} />
        {TYPE_ORDER.filter((t) => (counts[t] ?? 0) > 0).map((t) => (
          <Pill
            key={t}
            label={`${TYPE_LABELS[t]} (${counts[t]})`}
            active={typeFilter === t}
            onClick={() => setTypeFilter(t)}
          />
        ))}
      </div>

      {/* 工具栏 */}
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-6 pb-3">
        <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
          <input
            type="checkbox"
            className="h-4 w-4 accent-primary"
            checked={allSelected}
            onChange={(e) => (e.target.checked ? selectAll(visibleIds) : clearSelection())}
          />
          全选
        </label>
        <span className="text-sm text-ink-3">共 {filtered.length} 道题</span>
        <div className="flex-1" />
        <div className="flex items-center gap-2 text-sm text-ink-2">
          <ListFilter size={15} className="text-ink-3" />
          <Dropdown
            className="w-28"
            value={diffFilter}
            options={[{ value: 'all', label: '题目难度' }, ...DIFFICULTIES.map((d) => ({ value: d, label: d }))]}
            onChange={(v) => setDiffFilter(v as Difficulty | 'all')}
          />
        </div>
        <span className="rounded-full bg-primary-light px-2.5 py-1 text-xs text-primary">
          已选 {selectedIds.length} 题
        </span>
        <button
          type="button"
          onClick={() => setAssembling(true)}
          className="flex items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-sm font-medium text-white shadow-[0_4px_12px_rgba(30,111,255,0.30)] transition-all hover:bg-[#1a5fe6] active:scale-[0.97]"
        >
          <Users size={15} />
          组卷
        </button>
      </div>

      {/* 题目列表：滚轮滚动 */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-8 pt-4">
        {filtered.map((q, idx) => (
          <QuestionCard key={q.id} q={q} index={idx + 1} />
        ))}
        {!filtered.length && <div className="py-16 text-center text-sm text-ink-3">当前筛选条件下没有题目</div>}
      </div>

      {assembling && <AssembleModal onClose={() => setAssembling(false)} />}
    </div>
  )
}

function Pill({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg px-3.5 py-1.5 text-[14px] transition-colors ${
        active
          ? 'bg-primary font-medium text-white shadow-[0_2px_8px_rgba(30,111,255,0.30)]'
          : 'border border-line bg-white text-ink-2 hover:border-primary/50 hover:text-primary'
      }`}
    >
      {label}
    </button>
  )
}
