import { useState } from 'react'
import { Folder, Inbox, MoreHorizontal, Plus, Settings, Star } from 'lucide-react'
import type { FavoriteFolder } from '../../../types/favorites'

interface Props {
  folders: FavoriteFolder[]
  counts: Record<string, number>
  total: number
  activeFolder: string
  onSelect: (folderId: string) => void
  onCreate: () => void
  onRename: (folder: FavoriteFolder) => void
  onDelete: (folder: FavoriteFolder) => void
  onManage: () => void
}

/** A-2 收藏夹侧栏 */
export default function FavoritesRail({
  folders,
  counts,
  total,
  activeFolder,
  onSelect,
  onCreate,
  onRename,
  onDelete,
  onManage,
}: Props) {
  const [menuFor, setMenuFor] = useState<string | null>(null)

  const rowClass = (active: boolean) =>
    `flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors ${
      active ? 'bg-primary-light font-semibold text-primary' : 'text-ink-2 hover:bg-primary-weak hover:text-primary'
    }`

  return (
    <aside className="hidden w-[200px] shrink-0 flex-col rounded-2xl border border-line/80 bg-white p-3 shadow-[0_4px_16px_rgba(30,90,180,0.05)] lg:flex xl:w-[232px]">
      <div className="flex items-center justify-between px-1.5 pb-2">
        <h3 className="text-sm font-bold text-ink">收藏夹</h3>
        <button
          type="button"
          onClick={onCreate}
          title="新建收藏夹"
          aria-label="新建收藏夹"
          className="rounded-md p-1 text-ink-3 transition-colors hover:bg-primary-light hover:text-primary"
        >
          <Plus size={16} />
        </button>
      </div>

      <ul className="flex flex-col gap-0.5">
        <li>
          <button type="button" onClick={() => onSelect('all')} className={rowClass(activeFolder === 'all')}>
            <Star size={16} className={activeFolder === 'all' ? 'text-primary' : 'text-ink-3'} />
            <span className="flex-1 truncate">全部收藏</span>
            <span className="text-xs text-ink-3">{total}</span>
          </button>
        </li>
        {folders.map((folder) => {
          const active = activeFolder === folder.id
          const count = counts[folder.id] ?? 0
          return (
            <li key={folder.id} className="group relative">
              <div className="flex items-center rounded-lg">
                <button
                  type="button"
                  onClick={() => onSelect(folder.id)}
                  className={`${rowClass(active)} min-w-0 flex-1 ${folder.id === 'inbox' ? '' : 'pr-0'}`}
                >
                  {folder.id === 'inbox' ? (
                    <Inbox size={16} className={active ? 'text-primary' : 'text-ink-3'} />
                  ) : (
                    <Folder size={16} className={active ? 'text-primary' : 'text-ink-3'} />
                  )}
                  <span className="flex-1 truncate">{folder.name}</span>
                  <span className="text-xs text-ink-3 group-hover:hidden">{count}</span>
                </button>
                {folder.id !== 'inbox' && (
                  <button
                    type="button"
                    title="重命名 / 删除"
                    aria-label={`管理收藏夹 ${folder.name}`}
                    onClick={(event) => {
                      event.stopPropagation()
                      setMenuFor((current) => (current === folder.id ? null : folder.id))
                    }}
                    className="mr-1 hidden shrink-0 rounded-md p-1 text-ink-3 hover:bg-white hover:text-primary group-hover:block"
                  >
                    <MoreHorizontal size={15} />
                  </button>
                )}
              </div>
              {menuFor === folder.id && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setMenuFor(null)} />
                  <div className="absolute right-1 top-9 z-20 w-28 rounded-lg border border-line bg-white py-1 shadow-lg">
                    <button
                      type="button"
                      onClick={() => {
                        setMenuFor(null)
                        onRename(folder)
                      }}
                      className="block w-full px-3 py-2 text-left text-sm text-ink-2 hover:bg-primary-weak hover:text-primary"
                    >
                      重命名
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setMenuFor(null)
                        onDelete(folder)
                      }}
                      className="block w-full px-3 py-2 text-left text-sm text-danger hover:bg-[#fef2f2]"
                    >
                      删除
                    </button>
                  </div>
                </>
              )}
            </li>
          )
        })}
      </ul>

      <div className="mt-auto border-t border-dashed border-line/80 pt-3">
        <button
          type="button"
          onClick={onManage}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-ink-2 transition-colors hover:bg-primary-weak hover:text-primary"
        >
          <Settings size={14} />
          管理收藏夹
        </button>
        <p className="mt-2 px-2 text-xs leading-6 text-ink-3">
          在题目预览页点击 <span className="text-star">★</span> 即可收藏，并选择放入哪个收藏夹。
        </p>
      </div>
    </aside>
  )
}
