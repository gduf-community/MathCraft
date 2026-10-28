import { useEffect, useRef } from 'react'
import { ChevronsDown, ChevronsUp, LayoutGrid, List, RotateCcw, Search } from 'lucide-react'
import FavoritesDropdown from './FavoritesDropdown'
import { DIFFICULTIES, TYPE_LABELS, TYPE_ORDER } from '../../../constants'
import type { Difficulty, QuestionType } from '../../../types'

export type SortKey = 'recent' | 'oldest' | 'diff' | 'score'

/** 窄屏下排序下拉的短标签 */
const SORT_SHORT: Record<SortKey, string> = { recent: '最近', oldest: '最早', diff: '难度', score: '分值' }

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
  hasActiveFilters: boolean
  onClearFilters: () => void
  collapsed: boolean
  onToggleCollapsed: () => void
  summary: string
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
  hasActiveFilters,
  onClearFilters,
  collapsed,
  onToggleCollapsed,
  summary,
}: Props) {
  const selectAllRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = !allSelected && someSelected
  }, [allSelected, someSelected])

  if (collapsed) {
    return (
      <div className="flex h-10 shrink-0 items-center gap-2 rounded-xl border border-line/80 bg-white px-3 shadow-[0_4px_16px_rgba(30,90,180,0.04)]">
        <div className="relative w-[200px] shrink-0 sm:w-[240px] lg:w-[260px]">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            type="search"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="搜索题干、知识点或编号"
            aria-label="搜索收藏题目"
            className="h-8 w-full rounded-lg border border-line bg-white pl-9 pr-3 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
          />
        </div>
        <span className="hidden min-w-0 flex-1 truncate text-xs text-ink-2 sm:block" title={summary || '未设置筛选'}>
          {summary || '未设置筛选'}
        </span>
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-expanded="false"
          title="展开筛选"
          aria-label="展开筛选"
          className="ml-auto grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-primary-weak hover:text-primary sm:ml-0"
        >
          <ChevronsDown size={16} />
        </button>
        {hasActiveFilters && (
          <button
            type="button"
            onClick={onClearFilters}
            title="清空筛选"
            className="inline-flex h-8 shrink-0 items-center gap-1 rounded-lg border border-line bg-white px-2 text-xs text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
          >
            <RotateCcw size={13} />
            <span className="hidden sm:inline">清空筛选</span>
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="shrink-0 rounded-xl border border-line/80 bg-white px-3.5 py-2.5 shadow-[0_4px_16px_rgba(30,90,180,0.04)]">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex min-w-0 flex-1 flex-nowrap items-center gap-1.5 overflow-hidden py-1 -my-1 min-[1440px]:flex-wrap min-[1440px]:overflow-visible min-[1440px]:py-0 min-[1440px]:my-0">
          <button
            type="button"
            onClick={() => onTypeChange('all')}
            className={`shrink-0 whitespace-nowrap rounded-lg border px-3 py-1 text-sm transition-colors ${
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
              className={`shrink-0 whitespace-nowrap rounded-lg border px-3 py-1 text-sm transition-colors ${
                typeFilter === type
                  ? 'border-primary bg-primary font-medium text-white shadow-[0_2px_8px_rgba(30,111,255,0.3)]'
                  : 'border-line bg-white text-ink-2 hover:border-primary/50 hover:text-primary'
              }`}
            >
              {TYPE_LABELS[type]} ({typeCounts[type]})
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-expanded="true"
          title="收起筛选"
          className="order-2 flex shrink-0 items-center gap-1 rounded-lg px-1.5 py-1 text-xs text-ink-3 transition-colors hover:bg-primary-weak hover:text-primary 2xl:order-3"
        >
          收起筛选
          <ChevronsUp size={14} />
        </button>
        <div className="relative order-3 w-full 2xl:order-2 2xl:ml-auto 2xl:w-[280px]">
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

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line/70 pt-2.5 min-[1440px]:gap-x-2">
        <label className="order-1 flex cursor-pointer select-none items-center gap-2 text-sm text-ink-2">
          <input
            ref={selectAllRef}
            type="checkbox"
            checked={allSelected}
            onChange={(event) => onToggleAll(event.target.checked)}
            className="h-4 w-4 accent-primary"
          />
          全选
        </label>
        <span className="order-2 text-xs text-ink-3">
          共 <b className="text-primary">{filteredCount}</b> 题
          {selectedCount > 0 && (
            <>
              {' '}· 已选 <b className="text-primary">{selectedCount}</b> 题
            </>
          )}
        </span>

        {hasActiveFilters && (
          <button
            type="button"
            onClick={onClearFilters}
            className="order-3 inline-flex h-8 shrink-0 items-center gap-1 rounded-lg border border-line bg-white px-2 text-xs text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
          >
            <RotateCcw size={13} />
            清空筛选
          </button>
        )}

        <div className="order-5 basis-full min-[1440px]:ml-auto min-[1440px]:basis-auto">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 min-[1440px]:flex min-[1440px]:flex-wrap min-[1440px]:justify-end">
            <FavoritesDropdown
              className="w-full min-[1440px]:w-28"
              compactLabel={difficulty === 'all' ? '难度' : `难度·${difficulty}`}
              value={difficulty}
              options={[{ value: 'all', label: '全部难度' }, ...DIFFICULTIES.map((item) => ({ value: item, label: item }))]}
              onChange={(value) => onDifficultyChange(value as Difficulty | 'all')}
            />
            <FavoritesDropdown
              className="w-full min-[1440px]:w-32"
              compactLabel={knowledgePoint === 'all' ? '知识点' : `知识点·${knowledgePoint}`}
              value={knowledgePoint}
              options={[{ value: 'all', label: '全部知识点' }, ...knowledgePoints.map((item) => ({ value: item, label: item }))]}
              onChange={onKnowledgePointChange}
            />
            <FavoritesDropdown
              className="w-full min-[1440px]:w-32"
              compactLabel={source === 'all' ? '来源' : `来源·${source}`}
              value={source}
              options={[{ value: 'all', label: '全部来源' }, ...sources.map((item) => ({ value: item, label: item }))]}
              onChange={onSourceChange}
            />
            <FavoritesDropdown
              className="w-full min-[1440px]:w-32"
              compactLabel={`排序·${SORT_SHORT[sort]}`}
              value={sort}
              options={[
                { value: 'recent', label: '最近收藏' },
                { value: 'oldest', label: '最早收藏' },
                { value: 'diff', label: '难度从高到低' },
                { value: 'score', label: '分值从高到低' },
              ]}
              onChange={(value) => onSortChange(value as SortKey)}
            />
          </div>
        </div>

        <div
          className="order-4 ml-auto flex overflow-hidden rounded-lg border border-line min-[1440px]:order-6 min-[1440px]:ml-0"
          role="group"
          aria-label="视图切换"
        >
          <button
            type="button"
            title="卡片视图"
            aria-label="卡片视图"
            aria-pressed={view === 'card'}
            onClick={() => onViewChange('card')}
            className={`grid h-10 w-10 place-items-center transition-colors ${
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
            className={`grid h-10 w-10 place-items-center border-l border-line transition-colors ${
              view === 'compact' ? 'bg-primary-light text-primary' : 'bg-white text-ink-3 hover:text-primary'
            }`}
          >
            <List size={15} />
          </button>
        </div>
      </div>
    </div>
  )
}
