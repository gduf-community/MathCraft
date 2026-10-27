import { useEffect, useRef } from 'react'
import { LayoutGrid, List, Search } from 'lucide-react'
import Dropdown from '../../ui/Dropdown'
import { DIFFICULTIES, TYPE_LABELS, TYPE_ORDER } from '../../../constants'
import type { Difficulty, QuestionType } from '../../../types'

export type SortKey = 'recent' | 'oldest' | 'diff' | 'score'

interface Props {
  typeCounts: Record<string, number>
  typeFilter: QuestionType | 'all'
  onTypeChange: (value: QuestionType | 'all') => void
  query: string
  onQueryChange: (value: string) => void
  difficulty: Difficulty | 'all'
  onDifficultyChange: (value: Difficulty | 'all') => void
  knowledgePoint: string
  onKnowledgePointChange: (value: string) => void
  knowledgePoints: string[]
  source: string
  onSourceChange: (value: string) => void
  sources: string[]
  sort: SortKey
  onSortChange: (value: SortKey) => void
  view: 'card' | 'compact'
  onViewChange: (value: 'card' | 'compact') => void
  filteredCount: number
  selectedCount: number
  allSelected: boolean
  someSelected: boolean
  onToggleAll: (checked: boolean) => void
}

/** A-3/A-4/A-5/A-6：题型胶囊、搜索、筛选排序与全选 */
export default function FavoritesFilters({
  typeCounts,
  typeFilter,
  onTypeChange,
  query,
  onQueryChange,
  difficulty,
  onDifficultyChange,
  knowledgePoint,
  onKnowledgePointChange,
  knowledgePoints,
  source,
  onSourceChange,
  sources,
  sort,
  onSortChange,
  view,
  onViewChange,
  filteredCount,
  selectedCount,
  allSelected,
  someSelected,
  onToggleAll,
}: Props) {
  const selectAllRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = !allSelected && someSelected
  }, [allSelected, someSelected])

  return (
    <div className="rounded-xl border border-line/80 bg-white px-3.5 py-2.5 shadow-[0_4px_16px_rgba(30,90,180,0.04)]">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => onTypeChange('all')}
            className={`rounded-lg border px-3 py-1 text-sm transition-colors ${
              typeFilter === 'all'
                ? 'border-primary bg-primary font-medium text-white shadow-[0_2px_8px_rgba(30,111,255,0.3)]'
                : 'border-line bg-white text-ink-2 hover:border-primary/50 hover:text-primary'
            }`}
          >
            全部 ({typeCounts.all ?? 0})
          </button>
          {TYPE_ORDER.filter((type) => (typeCounts[type] ?? 0) > 0).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => onTypeChange(type)}
              className={`rounded-lg border px-3 py-1 text-sm transition-colors ${
                typeFilter === type
                  ? 'border-primary bg-primary font-medium text-white shadow-[0_2px_8px_rgba(30,111,255,0.3)]'
                  : 'border-line bg-white text-ink-2 hover:border-primary/50 hover:text-primary'
              }`}
            >
              {TYPE_LABELS[type]} ({typeCounts[type]})
            </button>
          ))}
        </div>
        <div className="flex-1" />
        <div className="relative min-w-[180px] max-w-[320px] flex-1 basis-52">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            type="search"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="搜索题干、知识点或编号"
            aria-label="搜索收藏题目"
            className="h-9 w-full rounded-lg border border-line bg-white pl-9 pr-3 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
          />
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-3 border-t border-line/70 pt-2.5">
        <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-ink-2">
          <input
            ref={selectAllRef}
            type="checkbox"
            checked={allSelected}
            onChange={(event) => onToggleAll(event.target.checked)}
            className="h-4 w-4 accent-primary"
          />
          全选
        </label>
        <span className="text-xs text-ink-3">
          共 <b className="text-primary">{filteredCount}</b> 题
          {selectedCount > 0 && (
            <>
              {' '}· 已选 <b className="text-primary">{selectedCount}</b> 题
            </>
          )}
        </span>
        <div className="flex-1" />

        <div className="flex flex-wrap items-center gap-2">
          <Dropdown
            className="w-28"
            value={difficulty}
            options={[{ value: 'all', label: '全部难度' }, ...DIFFICULTIES.map((item) => ({ value: item, label: item }))]}
            onChange={(value) => onDifficultyChange(value as Difficulty | 'all')}
          />
          <Dropdown
            className="w-32"
            value={knowledgePoint}
            options={[{ value: 'all', label: '全部知识点' }, ...knowledgePoints.map((item) => ({ value: item, label: item }))]}
            onChange={onKnowledgePointChange}
          />
          <Dropdown
            className="w-32"
            value={source}
            options={[{ value: 'all', label: '全部来源' }, ...sources.map((item) => ({ value: item, label: item }))]}
            onChange={onSourceChange}
          />
          <Dropdown
            className="w-32"
            value={sort}
            options={[
              { value: 'recent', label: '最近收藏' },
              { value: 'oldest', label: '最早收藏' },
              { value: 'diff', label: '难度从高到低' },
              { value: 'score', label: '分值从高到低' },
            ]}
            onChange={(value) => onSortChange(value as SortKey)}
          />
          <div className="flex overflow-hidden rounded-lg border border-line" role="group" aria-label="视图切换">
            <button
              type="button"
              title="卡片视图"
              aria-label="卡片视图"
              aria-pressed={view === 'card'}
              onClick={() => onViewChange('card')}
              className={`grid h-9 w-9 place-items-center transition-colors ${
                view === 'card' ? 'bg-primary-light text-primary' : 'bg-white text-ink-3 hover:text-primary'
              }`}
            >
              <LayoutGrid size={15} />
            </button>
            <button
              type="button"
              title="紧凑视图"
              aria-label="紧凑视图"
              aria-pressed={view === 'compact'}
              onClick={() => onViewChange('compact')}
              className={`grid h-9 w-9 place-items-center border-l border-line transition-colors ${
                view === 'compact' ? 'bg-primary-light text-primary' : 'bg-white text-ink-3 hover:text-primary'
              }`}
            >
              <List size={15} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
