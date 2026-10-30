import { useMemo, useRef, useState } from 'react'
import { CheckSquare, Download, Inbox, MoreHorizontal, Plus, Search, Trash2, Users, X } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { useFavorites } from '../../../store/FavoritesContext'
import { TYPE_LABELS } from '../../../constants'
import { isWithinWeek } from '../../../lib/relativeTime'
import type { Difficulty, QuestionType } from '../../../types'
import type { FavoriteFolder, FavoriteItem } from '../../../types/favorites'
import FavoriteCard from './FavoriteCard'
import FavoritesFilters from './FavoritesFilters'
import type { SortKey } from './FavoritesFilters'
import FavoritesRail from './FavoritesRail'
import { ConfirmModal, FolderFormModal, MoveFolderModal } from './FolderModal'
import ManageFoldersModal from './ManageFoldersModal'
import QuestionDetailModal from './QuestionDetailModal'

type FolderModalState =
  | { mode: 'create' }
  | { mode: 'rename'; folder: FavoriteFolder }
  | { mode: 'delete'; folder: FavoriteFolder }
  | null

const DIFF_RANK: Record<Difficulty, number> = { 低: 1, 中: 2, 高: 3, 地狱: 4 }

const RAIL_COLLAPSED_KEY = 'mcraft.favorites.railCollapsed'
const FILTERS_COLLAPSED_KEY = 'mcraft.favorites.filtersCollapsed'

/** 折叠状态读写 localStorage；隐私模式下读写失败时回退为展开 */
function useStoredFlag(key: string) {
  const [value, setValue] = useState(() => {
    try {
      return window.localStorage.getItem(key) === '1'
    } catch {
      return false
    }
  })
  const toggle = () =>
    setValue((prev) => {
      const next = !prev
      try {
        window.localStorage.setItem(key, next ? '1' : '0')
      } catch {
        /* 忽略存储异常 */
      }
      return next
    })
  return [value, toggle] as const
}

/** 题目收藏页：收藏夹、筛选、只读卡片、批量操作与撤销 */
export default function FavoritesTab() {
  const { setActiveTab, showToast } = useApp()
  const {
    items,
    folders,
    folderCounts,
    loading,
    pendingAssembleCount,
    removeFavorite,
    restoreFavorite,
    createFolder,
    renameFolder,
    deleteFolder,
    reorderFolders,
    moveFavorites,
    addToAssemble,
  } = useFavorites()

  const [folderFilter, setFolderFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState<QuestionType | 'all'>('all')
  const [difficultyFilter, setDifficultyFilter] = useState<Difficulty | 'all'>('all')
  const [knowledgeFilter, setKnowledgeFilter] = useState('all')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [sort, setSort] = useState<SortKey>('recent')
  const [view, setView] = useState<'card' | 'compact'>('card')
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(6)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [folderModal, setFolderModal] = useState<FolderModalState>(null)
  const [moveOpen, setMoveOpen] = useState(false)
  const [mobileMenu, setMobileMenu] = useState<{ folder: FavoriteFolder; left: number; top: number } | null>(null)
  const [manageOpen, setManageOpen] = useState(false)
  const [detailItem, setDetailItem] = useState<FavoriteItem | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const manageButtonRef = useRef<HTMLButtonElement>(null)
  const detailTriggerRef = useRef<HTMLButtonElement | null>(null)
  const [railCollapsed, toggleRail] = useStoredFlag(RAIL_COLLAPSED_KEY)
  const [filtersCollapsed, toggleFilters] = useStoredFlag(FILTERS_COLLAPSED_KEY)

  const resetView = () => {
    setLimit(6)
    setSelectedIds([])
  }

  const folderNameById = useMemo(() => {
    const map: Record<string, string> = { inbox: '未分类' }
    for (const folder of folders) map[folder.id] = folder.name
    return map
  }, [folders])

  const base = useMemo(
    () => (folderFilter === 'all' ? items : items.filter((item) => item.folderId === folderFilter)),
    [items, folderFilter],
  )

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = { all: base.length }
    for (const item of base) {
      counts[item.question.type] = (counts[item.question.type] ?? 0) + 1
    }
    return counts
  }, [base])

  const knowledgePoints = useMemo(
    () => [...new Set(items.map((item) => item.question.knowledgePoint).filter(Boolean))],
    [items],
  )

  const sources = useMemo(
    () => [...new Set(items.map((item) => item.source.bankName).filter((value): value is string => Boolean(value)))],
    [items],
  )

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    const list = base.filter((item) => {
      const q = item.question
      if (typeFilter !== 'all' && q.type !== typeFilter) return false
      if (difficultyFilter !== 'all' && q.difficulty !== difficultyFilter) return false
      if (knowledgeFilter !== 'all' && q.knowledgePoint !== knowledgeFilter) return false
      if (sourceFilter !== 'all' && item.source.bankName !== sourceFilter) return false
      if (keyword) {
        const haystack = [
          q.stem,
          q.knowledgePoint,
          q.id,
          item.source.bankName,
          item.source.chapter,
          TYPE_LABELS[q.type],
          folderNameById[item.folderId],
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
        if (!haystack.includes(keyword)) return false
      }
      return true
    })
    return list.sort((a, b) => {
      if (sort === 'oldest') return a.collectedAt.localeCompare(b.collectedAt)
      if (sort === 'diff') {
        return (
          DIFF_RANK[b.question.difficulty] - DIFF_RANK[a.question.difficulty] ||
          b.collectedAt.localeCompare(a.collectedAt)
        )
      }
      if (sort === 'score') {
        return b.question.score - a.question.score || b.collectedAt.localeCompare(a.collectedAt)
      }
      return b.collectedAt.localeCompare(a.collectedAt)
    })
  }, [base, typeFilter, difficultyFilter, knowledgeFilter, sourceFilter, query, sort, folderNameById])

  const visible = filtered.slice(0, limit)
  const selectedItems = items.filter((item) => selectedIds.includes(item.id))
  const selectedScore = selectedItems.reduce((sum, item) => sum + item.question.score, 0)
  const allSelected = filtered.length > 0 && filtered.every((item) => selectedIds.includes(item.id))
  const someSelected = filtered.some((item) => selectedIds.includes(item.id))
  const baseEmpty = base.length === 0
  const noResult = !baseEmpty && filtered.length === 0

  const total = items.length
  const knowledgeCount = new Set(items.map((item) => item.question.knowledgePoint).filter(Boolean)).size
  const weekCount = items.filter((item) => isWithinWeek(item.collectedAt)).length

  const toggleAll = (checked: boolean) => {
    const ids = new Set(filtered.map((item) => item.id))
    setSelectedIds((prev) => (checked ? [...new Set([...prev, ...ids])] : prev.filter((id) => !ids.has(id))))
  }

  const removeItem = async (item: FavoriteItem) => {
    const removed = await removeFavorite(item.id)
    if (!removed) return
    setSelectedIds((prev) => prev.filter((id) => id !== item.id))
    showToast(`已取消收藏「${item.question.knowledgePoint}」`, {
      actionLabel: '撤销',
      duration: 5000,
      onAction: () => {
        void restoreFavorite(removed)
        setSelectedIds((prev) => (prev.includes(item.id) ? prev : [...prev, item.id]))
      },
    })
  }

  const removeSelected = async () => {
    // 按当前列表顺序取快照，撤销时按同一顺序插回
    const removing = filtered.filter((item) => selectedIds.includes(item.id))
    if (!removing.length) return
    const previousSelection = [...selectedIds]
    const removed: FavoriteItem[] = []
    for (const item of removing) {
      const snapshot = await removeFavorite(item.id)
      if (snapshot) removed.push(snapshot)
    }
    if (!removed.length) return
    const removedIds = new Set(removed.map((item) => item.id))
    setSelectedIds([])
    showToast(`已移出 ${removed.length} 题`, {
      actionLabel: '撤销',
      duration: 5000,
      onAction: () => {
        void (async () => {
          for (const snapshot of removed) await restoreFavorite(snapshot)
          setSelectedIds((prev) => [
            ...new Set([...prev, ...previousSelection.filter((id) => removedIds.has(id))]),
          ])
        })()
      },
    })
  }

  const addAssemble = (count: number, detail: string) => {
    if (count <= 0) {
      showToast('当前没有可加入组卷的题目')
      return
    }
    addToAssemble(count)
    showToast(`${detail}（本次共 ${pendingAssembleCount + count} 道）`)
  }

  const handleHeaderAssemble = () => {
    if (selectedItems.length) {
      addAssemble(selectedItems.length, `已把 ${selectedItems.length} 道题加入组卷清单`)
      return
    }
    addAssemble(filtered.length, `已按当前筛选结果加入组卷清单 ${filtered.length} 道`)
  }

  const hasActiveFilters =
    typeFilter !== 'all' ||
    difficultyFilter !== 'all' ||
    knowledgeFilter !== 'all' ||
    sourceFilter !== 'all' ||
    query.trim() !== ''

  const filterSummary = [
    typeFilter !== 'all' ? TYPE_LABELS[typeFilter] : '',
    difficultyFilter !== 'all' ? difficultyFilter : '',
    knowledgeFilter !== 'all' ? knowledgeFilter : '',
    sourceFilter !== 'all' ? sourceFilter : '',
    query.trim() ? `搜索：${query.trim()}` : '',
  ]
    .filter(Boolean)
    .join(' · ')

  const clearFilters = () => {
    setTypeFilter('all')
    setDifficultyFilter('all')
    setKnowledgeFilter('all')
    setSourceFilter('all')
    setQuery('')
    resetView()
    scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const submitFolder = async (name: string, description: string) => {
    if (!folderModal || folderModal.mode === 'delete') return false
    try {
      if (folderModal.mode === 'create') {
        const folder = await createFolder(name, description)
        setFolderFilter(folder.id)
        showToast(`已创建收藏夹「${folder.name}」`)
      } else {
        await renameFolder(folderModal.folder.id, name, description)
        showToast('收藏夹已重命名')
      }
      setFolderModal(null)
      resetView()
      return true
    } catch (error) {
      showToast(error instanceof Error ? error.message : '操作失败')
      return false
    }
  }

  const confirmDelete = async () => {
    if (folderModal?.mode !== 'delete') return
    const folder = folderModal.folder
    const count = folderCounts[folder.id] ?? 0
    try {
      await deleteFolder(folder.id)
      if (folderFilter === folder.id) setFolderFilter('inbox')
      setFolderModal(null)
      resetView()
      showToast(`已删除收藏夹「${folder.name}」，${count} 道题已移至未分类`)
    } catch (error) {
      showToast(error instanceof Error ? error.message : '删除失败')
    }
  }

  const selectFolder = (folderId: string) => {
    setFolderFilter(folderId)
    resetView()
  }

  const closeManage = () => {
    setManageOpen(false)
    manageButtonRef.current?.focus()
  }

  const openFolder = (folderId: string) => {
    selectFolder(folderId)
    scrollRef.current?.scrollTo({ top: 0 })
    closeManage()
  }

  const openDetail = (item: FavoriteItem, trigger: HTMLButtonElement) => {
    detailTriggerRef.current = trigger
    setDetailItem(item)
  }

  const closeDetail = () => {
    setDetailItem(null)
    requestAnimationFrame(() => detailTriggerRef.current?.focus())
  }

  const handleMove = async (folderId: string) => {
    try {
      const count = selectedItems.length
      await moveFavorites(selectedIds, folderId)
      setMoveOpen(false)
      setSelectedIds([])
      showToast(`已把 ${count} 道题移动到「${folderNameById[folderId] ?? '收藏夹'}」`)
    } catch (error) {
      showToast(error instanceof Error ? error.message : '移动失败')
    }
  }

  const mobileFolders = [
    { id: 'all', name: '全部收藏', count: total },
    ...folders.map((folder) => ({ id: folder.id, name: folder.name, count: folderCounts[folder.id] ?? 0 })),
  ]

  return (
    <div className="relative flex min-h-0 flex-1 flex-col bg-[#f5f8fd]">
      <header className="flex shrink-0 flex-wrap items-end justify-between gap-4 px-6 pb-3 pt-4 xl:px-8 xl:pb-4 xl:pt-5">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[21px] font-bold text-ink">题目收藏</h2>
            <span className="rounded border border-line/80 bg-white px-1.5 py-0.5 text-[11px] text-ink-3">
              演示数据 · 刷新后重置
            </span>
          </div>
          <p className="mt-1.5 text-sm text-ink-2">集中管理已收藏的题目，可随时组卷、补充解析或整理进收藏夹。</p>
        </div>
        <div className="flex flex-wrap items-center gap-5">
          <div className="flex items-center gap-4">
            <Stat value={total} label="收藏总数" first />
            <Stat value={knowledgeCount} label="覆盖知识点" />
            <Stat value={weekCount} label="本周新增" />
          </div>
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => showToast('导出当前收藏夹题目（Word / CSV 二选一）')}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line bg-white px-3.5 text-sm text-ink-2 transition-colors hover:border-primary/50 hover:bg-primary-weak hover:text-primary"
            >
              <Download size={15} />
              导出
            </button>
            <button
              type="button"
              onClick={handleHeaderAssemble}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-medium text-white shadow-[0_4px_14px_rgba(30,111,255,0.32)] transition-colors hover:bg-[#1a5fe6]"
            >
              <Users size={15} />
              组卷
            </button>
          </div>
        </div>
      </header>

      <div className={`flex min-h-0 flex-1 gap-4 px-6 xl:px-8 ${selectedItems.length ? 'pb-24' : 'pb-6'}`}>
        <FavoritesRail
          folders={folders}
          counts={folderCounts}
          total={total}
          activeFolder={folderFilter}
          onSelect={selectFolder}
          onCreate={() => setFolderModal({ mode: 'create' })}
          onRename={(folder) => setFolderModal({ mode: 'rename', folder })}
          onDelete={(folder) => setFolderModal({ mode: 'delete', folder })}
          onManage={() => setManageOpen(true)}
          collapsed={railCollapsed}
          onToggle={toggleRail}
          manageButtonRef={manageButtonRef}
        />

        <section className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="flex shrink-0 flex-nowrap items-start gap-2 overflow-hidden pb-1 lg:hidden">
            {mobileFolders.map((folder) => {
              const active = folderFilter === folder.id
              const manageable = folder.id !== 'all' && folder.id !== 'inbox'
              return (
                <div
                  key={folder.id}
                  className={`flex shrink-0 items-center rounded-lg border text-xs transition-colors ${
                    active ? 'border-primary bg-primary text-white' : 'border-line bg-white text-ink-2'
                  }`}
                >
                  <button
                    type="button"
                    title={folder.name}
                    onClick={() => selectFolder(folder.id)}
                    className={`max-w-[160px] truncate py-1.5 pl-3 ${manageable ? 'pr-1.5' : 'pr-3'}`}
                  >
                    {folder.name} ({folder.count})
                  </button>
                  {manageable && (
                    <button
                      type="button"
                      title="重命名 / 删除"
                      aria-label={`管理收藏夹 ${folder.name}`}
                      onClick={(event) => {
                        const item = folders.find((value) => value.id === folder.id)
                        if (!item) return
                        const rect = event.currentTarget.getBoundingClientRect()
                        setMobileMenu({
                          folder: item,
                          left: Math.max(8, Math.min(rect.left, window.innerWidth - 112)),
                          top: rect.bottom + 4,
                        })
                      }}
                      className={`py-1.5 pl-0.5 pr-2 ${
                        active ? 'text-white/80 hover:text-white' : 'text-ink-3 hover:text-primary'
                      }`}
                    >
                      <MoreHorizontal size={14} />
                    </button>
                  )}
                </div>
              )
            })}
            <button
              type="button"
              onClick={() => setFolderModal({ mode: 'create' })}
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-dashed border-line bg-white px-3 py-1.5 text-xs text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
            >
              <Plus size={13} />
              新建收藏夹
            </button>
          </div>

          <FavoritesFilters
            typeCounts={typeCounts}
            typeFilter={typeFilter}
            onTypeChange={(value) => {
              setTypeFilter(value)
              resetView()
            }}
            query={query}
            onQueryChange={(value) => {
              setQuery(value)
              resetView()
            }}
            difficulty={difficultyFilter}
            onDifficultyChange={(value) => {
              setDifficultyFilter(value)
              resetView()
            }}
            knowledgePoint={knowledgeFilter}
            onKnowledgePointChange={(value) => {
              setKnowledgeFilter(value)
              resetView()
            }}
            knowledgePoints={knowledgePoints}
            source={sourceFilter}
            onSourceChange={(value) => {
              setSourceFilter(value)
              resetView()
            }}
            sources={sources}
            sort={sort}
            onSortChange={(value) => {
              setSort(value)
              resetView()
            }}
            view={view}
            onViewChange={setView}
            filteredCount={filtered.length}
            selectedCount={selectedItems.length}
            allSelected={allSelected}
            someSelected={someSelected}
            onToggleAll={toggleAll}
            hasActiveFilters={hasActiveFilters}
            onClearFilters={clearFilters}
            collapsed={filtersCollapsed}
            onToggleCollapsed={toggleFilters}
            summary={filterSummary}
          />

          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto pr-1">
            {loading ? (
              <div className="flex h-full items-center justify-center text-sm text-ink-3">正在加载收藏…</div>
            ) : baseEmpty || noResult ? (
              <div className="flex h-full flex-col items-center justify-center gap-2.5 py-16 text-center text-ink-3">
                <span className="grid h-14 w-14 place-items-center rounded-full bg-primary-light text-primary">
                  {baseEmpty ? <Inbox size={26} /> : <Search size={26} />}
                </span>
                <h4 className="text-base font-semibold text-ink">
                  {baseEmpty ? '这个收藏夹还是空的' : '没有找到匹配的题目'}
                </h4>
                <p className="max-w-sm text-sm leading-7">
                  {baseEmpty
                    ? '在题目预览页点击 ★ 收藏题目，之后可以在这里统一组卷。'
                    : '试试更换关键词，或清空筛选条件后重新查看。'}
                </p>
                <button
                  type="button"
                  onClick={() => (baseEmpty ? setActiveTab('generate') : clearFilters())}
                  className={`mt-1 inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                    baseEmpty
                      ? 'bg-primary text-white shadow-[0_4px_14px_rgba(30,111,255,0.32)] hover:bg-[#1a5fe6]'
                      : 'border border-line bg-white text-ink-2 hover:border-primary/50 hover:text-primary'
                  }`}
                >
                  {baseEmpty ? '去智能出题' : '清空筛选'}
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                {visible.map((item) => (
                  <FavoriteCard
                    key={item.id}
                    item={item}
                    folderName={folderNameById[item.folderId] ?? '未分类'}
                    selected={selectedIds.includes(item.id)}
                    compact={view === 'compact'}
                    onOpen={(trigger) => openDetail(item, trigger)}
                    onToggleSelect={() =>
                      setSelectedIds((prev) =>
                        prev.includes(item.id) ? prev.filter((id) => id !== item.id) : [...prev, item.id],
                      )
                    }
                    onRemove={() => void removeItem(item)}
                    onAssemble={() =>
                      addAssemble(
                        1,
                        `已加入组卷清单：${TYPE_LABELS[item.question.type]} · ${item.question.knowledgePoint}`,
                      )
                    }
                    onEdit={() => showToast('本期题目卡片只读，编辑能力待接入')}
                  />
                ))}
              </div>
            )}
          </div>

          {!loading && filtered.length > 0 && (
            <div className="flex shrink-0 items-center justify-center gap-3 pt-1 text-xs text-ink-3">
              {filtered.length > limit ? (
                <>
                  <button
                    type="button"
                    onClick={() => setLimit((value) => value + 6)}
                    className="inline-flex h-9 items-center rounded-lg border border-line bg-white px-4 text-sm text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
                  >
                    加载更多
                  </button>
                  <span>
                    已显示 {Math.min(limit, filtered.length)} / {filtered.length} 题
                  </span>
                </>
              ) : (
                <span>已展示全部 {filtered.length} 题</span>
              )}
            </div>
          )}
        </section>
      </div>

      {selectedItems.length > 0 && (
        <div className="absolute inset-x-4 bottom-4 z-20 flex flex-wrap items-center gap-2.5 rounded-xl border border-primary/25 bg-white px-4 py-2.5 shadow-[0_10px_30px_rgba(20,50,110,0.12)] xl:inset-x-6">
          <span className="flex items-center gap-1.5 text-sm text-ink-2">
            <CheckSquare size={16} className="text-primary" />
            已选 <b className="text-primary">{selectedItems.length}</b> 题 · 合计{' '}
            <b className="text-primary">{selectedScore}</b> 分
          </span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => setMoveOpen(true)}
            className="inline-flex h-8 items-center rounded-lg border border-line bg-white px-3 text-xs font-medium text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
          >
            移动到收藏夹
          </button>
          <button
            type="button"
            onClick={() => void removeSelected()}
            aria-label={`移出收藏（${selectedItems.length} 题）`}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-red-200 bg-[#fef2f2] px-3 text-xs font-medium text-danger transition-colors hover:bg-[#fee2e2]"
          >
            <Trash2 size={13} />
            移出收藏
          </button>
          <button
            type="button"
            onClick={() => showToast('导出已选题目（Word / CSV 二选一）')}
            className="inline-flex h-8 items-center rounded-lg border border-line bg-white px-3 text-xs font-medium text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
          >
            导出
          </button>
          <button
            type="button"
            onClick={() => addAssemble(selectedItems.length, `已把 ${selectedItems.length} 道题加入组卷清单`)}
            className="inline-flex h-8 items-center rounded-lg bg-primary px-3.5 text-xs font-medium text-white transition-colors hover:bg-[#1a5fe6]"
          >
            加入组卷
          </button>
          <button
            type="button"
            onClick={() => setSelectedIds([])}
            aria-label="取消选择"
            className="grid h-8 w-8 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-page hover:text-ink"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {mobileMenu && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setMobileMenu(null)} />
          <div
            className="fixed z-40 w-28 rounded-lg border border-line bg-white py-1 shadow-lg"
            style={{ left: mobileMenu.left, top: mobileMenu.top }}
          >
            <button
              type="button"
              onClick={() => {
                setFolderModal({ mode: 'rename', folder: mobileMenu.folder })
                setMobileMenu(null)
              }}
              className="block w-full px-3 py-2 text-left text-sm text-ink-2 hover:bg-primary-weak hover:text-primary"
            >
              重命名
            </button>
            <button
              type="button"
              onClick={() => {
                setFolderModal({ mode: 'delete', folder: mobileMenu.folder })
                setMobileMenu(null)
              }}
              className="block w-full px-3 py-2 text-left text-sm text-danger hover:bg-[#fef2f2]"
            >
              删除
            </button>
          </div>
        </>
      )}

      {manageOpen && (
        <ManageFoldersModal
          folders={folders}
          counts={folderCounts}
          total={total}
          childOpen={folderModal !== null}
          onClose={closeManage}
          onCreate={() => setFolderModal({ mode: 'create' })}
          onRename={(folder) => setFolderModal({ mode: 'rename', folder })}
          onDelete={(folder) => setFolderModal({ mode: 'delete', folder })}
          onReorder={(ids) => void reorderFolders(ids)}
          onOpen={openFolder}
        />
      )}

      {folderModal && folderModal.mode !== 'delete' && (
        <FolderFormModal
          folder={folderModal.mode === 'rename' ? folderModal.folder : undefined}
          onClose={() => setFolderModal(null)}
          onSubmit={submitFolder}
        />
      )}

      {folderModal?.mode === 'delete' && (
        <ConfirmModal
          title="删除收藏夹"
          message="确定删除该收藏夹？题目将移至未分类"
          confirmText="删除"
          onClose={() => setFolderModal(null)}
          onConfirm={() => void confirmDelete()}
        />
      )}

      {moveOpen && (
        <MoveFolderModal
          folders={folders}
          currentFolderId={folderFilter === 'all' ? undefined : folderFilter}
          count={selectedItems.length}
          onClose={() => setMoveOpen(false)}
          onMove={handleMove}
        />
      )}

      {detailItem && (
        <QuestionDetailModal
          item={detailItem}
          folderName={folderNameById[detailItem.folderId] ?? '未分类'}
          onClose={closeDetail}
        />
      )}
    </div>
  )
}

function Stat({ value, label, first }: { value: number; label: string; first?: boolean }) {
  return (
    <div className={`flex flex-col ${first ? '' : 'border-l border-line pl-4'}`}>
      <b className="text-lg font-bold leading-tight text-ink">{value}</b>
      <span className="text-xs text-ink-3">{label}</span>
    </div>
  )
}
