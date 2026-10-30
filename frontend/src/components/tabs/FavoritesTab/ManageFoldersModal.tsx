import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'
import {
  ChevronDown,
  ChevronUp,
  Folder,
  GripVertical,
  Inbox,
  Pencil,
  Plus,
  Search,
  Star,
  Trash2,
  X,
} from 'lucide-react'
import type { FavoriteFolder } from '../../../types/favorites'

interface Props {
  folders: FavoriteFolder[]
  counts: Record<string, number>
  total: number
  /** 重命名 / 删除 / 新建弹窗是否已打开，打开时暂停本弹窗的 Esc 处理 */
  childOpen: boolean
  onClose: () => void
  onCreate: () => void
  onRename: (folder: FavoriteFolder) => void
  onDelete: (folder: FavoriteFolder) => void
  onReorder: (orderedIds: string[]) => void
  onOpen: (folderId: string) => void
}

type DropPosition = 'before' | 'after'

/** 收藏夹管理弹窗：搜索、重命名 / 删除、拖拽与按钮排序自建收藏夹 */
export default function ManageFoldersModal({
  folders,
  counts,
  total,
  childOpen,
  onClose,
  onCreate,
  onRename,
  onDelete,
  onReorder,
  onOpen,
}: Props) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const wasChildOpen = useRef(childOpen)

  const [query, setQuery] = useState('')
  const [dragId, setDragId] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState<{ id: string; position: DropPosition } | null>(null)

  const keyword = query.trim().toLowerCase()
  const searching = keyword.length > 0
  const inboxFolder = folders.find((folder) => folder.id === 'inbox')
  const customFolders = folders.filter((folder) => folder.id !== 'inbox')
  const visibleFolders = searching
    ? customFolders.filter((folder) => folder.name.toLowerCase().includes(keyword))
    : customFolders

  useEffect(() => {
    closeRef.current?.focus()
  }, [])

  useEffect(() => {
    if (childOpen) return
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, childOpen])

  // 子弹窗（重命名 / 删除确认 / 新建）关闭后，把焦点交还本弹窗
  useEffect(() => {
    if (wasChildOpen.current && !childOpen) closeRef.current?.focus()
    wasChildOpen.current = childOpen
  }, [childOpen])

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

  const stopDrag = (event: PointerEvent<HTMLElement>) => {
    event.stopPropagation()
  }

  const moveBy = (id: string, direction: -1 | 1) => {
    if (searching) return
    const ids = customFolders.map((folder) => folder.id)
    const index = ids.indexOf(id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= ids.length) return
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    onReorder(ids)
  }

  const dropAt = (targetId: string, position: DropPosition) => {
    if (!dragId || searching || dragId === targetId) return
    const ids = customFolders.map((folder) => folder.id)
    if (!ids.includes(dragId)) return
    const next = ids.filter((id) => id !== dragId)
    let target = next.indexOf(targetId)
    if (target < 0) return
    if (position === 'after') target += 1
    next.splice(target, 0, dragId)
    onReorder(next)
  }

  const clearDrag = () => {
    setDragId(null)
    setDragOver(null)
  }

  return (
    <div
      className="fixed inset-0 z-40 flex animate-fade-in items-center justify-center bg-[#0f1b33]/30 p-6"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="manage-folders-title"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={trapFocus}
        className={`flex max-h-[80vh] w-full max-w-[520px] animate-pop flex-col rounded-2xl bg-white p-5 shadow-2xl ${
          dragId ? 'select-none' : ''
        }`}
      >
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h3 id="manage-folders-title" className="text-[17px] font-bold text-ink">
              管理收藏夹
            </h3>
            <p className="mt-1 text-xs leading-6 text-ink-3">
              重命名、删除或拖拽排序自建收藏夹；删除后夹内题目会回到「未分类」，题目本身不会删除。
            </p>
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
        </div>

        <div className="relative mt-3 shrink-0">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索收藏夹名称"
            aria-label="搜索收藏夹"
            className="h-9 w-full rounded-lg border border-line bg-white pl-9 pr-3 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
          />
        </div>

        <ul className="mt-3 min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
          <li>
            <div className="flex items-center gap-3 rounded-lg border border-line px-3 py-2.5">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary-light text-primary">
                <Star size={16} />
              </span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">全部收藏</span>
              <span className="shrink-0 text-xs text-ink-3">{total} 题</span>
              <button
                type="button"
                onClick={() => onOpen('all')}
                title="打开收藏夹"
                aria-label="打开收藏夹 全部收藏"
                className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-line bg-white px-2 text-xs text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
              >
                打开
              </button>
            </div>
          </li>
          {inboxFolder && (
            <li>
              <div className="flex items-center gap-3 rounded-lg border border-line px-3 py-2.5">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-page text-ink-3">
                  <Inbox size={16} />
                </span>
                <span className="min-w-0 flex-1 truncate text-sm text-ink" title={inboxFolder.name}>
                  {inboxFolder.name}
                </span>
                <span className="shrink-0 text-xs text-ink-3">{counts[inboxFolder.id] ?? 0} 题</span>
                <button
                  type="button"
                  onClick={() => onOpen(inboxFolder.id)}
                  title="打开收藏夹"
                  aria-label={`打开收藏夹 ${inboxFolder.name}`}
                  className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-line bg-white px-2 text-xs text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
                >
                  打开
                </button>
              </div>
            </li>
          )}
          {visibleFolders.map((folder) => {
            const index = customFolders.findIndex((item) => item.id === folder.id)
            const first = index <= 0
            const last = index >= customFolders.length - 1
            const dragging = dragId === folder.id
            const drop = dragOver?.id === folder.id ? dragOver.position : null
            return (
              <li key={folder.id}>
                <div
                  draggable={!searching}
                  onDragStart={(event) => {
                    if (searching) return
                    setDragId(folder.id)
                    event.dataTransfer.effectAllowed = 'move'
                    event.dataTransfer.setData('text/plain', folder.id)
                  }}
                  onDragOver={(event) => {
                    if (searching || !dragId || dragId === folder.id) return
                    event.preventDefault()
                    const rect = event.currentTarget.getBoundingClientRect()
                    const position: DropPosition =
                      event.clientY < rect.top + rect.height / 2 ? 'before' : 'after'
                    setDragOver((prev) =>
                      prev?.id === folder.id && prev.position === position
                        ? prev
                        : { id: folder.id, position },
                    )
                    try {
                      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
                    } catch {
                      /* 合成事件的 dataTransfer 可能只读 */
                    }
                  }}
                  onDrop={(event) => {
                    event.preventDefault()
                    const position =
                      dragOver?.id === folder.id ? dragOver.position : ('after' as DropPosition)
                    dropAt(folder.id, position)
                    clearDrag()
                  }}
                  onDragEnd={clearDrag}
                  className={`relative flex items-center gap-2.5 rounded-lg border px-2.5 py-2.5 transition-colors ${
                    dragging ? 'border-primary/40 bg-primary-weak/60 opacity-60' : 'border-line bg-white'
                  }`}
                >
                  <span
                    title={searching ? '清空搜索后可排序' : '拖动排序'}
                    className={`shrink-0 ${
                      searching ? 'cursor-not-allowed text-ink-3/40' : 'cursor-grab text-ink-3 active:cursor-grabbing'
                    }`}
                  >
                    <GripVertical size={15} />
                  </span>
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary-light/70 text-primary">
                    <Folder size={16} />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm text-ink" title={folder.name}>
                    {folder.name}
                  </span>
                  <span className="shrink-0 text-xs text-ink-3">{counts[folder.id] ?? 0} 题</span>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      onPointerDown={stopDrag}
                      onClick={() => moveBy(folder.id, -1)}
                      disabled={searching || first}
                      title={searching ? '清空搜索后可排序' : '上移'}
                      aria-label={`上移 ${folder.name}`}
                      className="grid h-7 w-7 place-items-center rounded-md border border-line bg-white text-ink-3 transition-colors hover:border-primary/50 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <ChevronUp size={14} />
                    </button>
                    <button
                      type="button"
                      onPointerDown={stopDrag}
                      onClick={() => moveBy(folder.id, 1)}
                      disabled={searching || last}
                      title={searching ? '清空搜索后可排序' : '下移'}
                      aria-label={`下移 ${folder.name}`}
                      className="grid h-7 w-7 place-items-center rounded-md border border-line bg-white text-ink-3 transition-colors hover:border-primary/50 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <ChevronDown size={14} />
                    </button>
                    <button
                      type="button"
                      onPointerDown={stopDrag}
                      onClick={() => onOpen(folder.id)}
                      title="打开收藏夹"
                      aria-label={`打开收藏夹 ${folder.name}`}
                      className="inline-flex h-7 items-center rounded-md border border-line bg-white px-2 text-xs text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
                    >
                      打开
                    </button>
                    <button
                      type="button"
                      onPointerDown={stopDrag}
                      onClick={() => onRename(folder)}
                      aria-label={`重命名收藏夹 ${folder.name}`}
                      className="inline-flex h-7 items-center gap-1 rounded-md border border-line bg-white px-2 text-xs text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
                    >
                      <Pencil size={12} />
                      重命名
                    </button>
                    <button
                      type="button"
                      onPointerDown={stopDrag}
                      onClick={() => onDelete(folder)}
                      aria-label={`删除收藏夹 ${folder.name}`}
                      className="inline-flex h-7 items-center gap-1 rounded-md border border-red-200 bg-[#fef2f2] px-2 text-xs text-danger transition-colors hover:bg-[#fee2e2]"
                    >
                      <Trash2 size={12} />
                      删除
                    </button>
                  </div>
                  {drop && (
                    <span
                      className={`pointer-events-none absolute inset-x-1 h-0.5 rounded-full bg-primary ${
                        drop === 'before' ? '-top-1' : '-bottom-1'
                      }`}
                    />
                  )}
                </div>
              </li>
            )
          })}
          {!searching && customFolders.length === 0 && (
            <li>
              <p className="rounded-lg bg-page px-3 py-4 text-center text-xs leading-6 text-ink-3">
                还没有自建收藏夹，点击下方「新建收藏夹」按专题归类题目。
              </p>
            </li>
          )}
          {searching && visibleFolders.length === 0 && (
            <li>
              <p className="rounded-lg bg-page px-3 py-4 text-center text-xs leading-6 text-ink-3">
                没有匹配的收藏夹
              </p>
            </li>
          )}
        </ul>

        <div className="mt-4 flex shrink-0 items-center justify-end border-t border-line pt-4">
          <button
            type="button"
            onClick={onCreate}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-[0_4px_14px_rgba(30,111,255,0.32)] transition-colors hover:bg-[#1a5fe6]"
          >
            <Plus size={15} />
            新建收藏夹
          </button>
        </div>
      </div>
    </div>
  )
}
