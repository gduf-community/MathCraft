/** 收藏分组弹窗：点亮星标时弹出，搜索并选择收藏分组，与题目收藏页实时联动 */
import { useMemo, useState } from 'react'
import { Folder, Search, X } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import type { Question } from '../../types'

interface Props {
  question: Question
  onClose: () => void
}

export default function FavoriteGroupModal({ question, onClose }: Props) {
  const { favGroups, favorites, addToFavorites, setFavoriteGroup, showToast } = useApp()
  const [search, setSearch] = useState('')
  const [picked, setPicked] = useState<string>(() => favorites.find((f) => f.id === question.id)?.favGroupId ?? favGroups.find((g) => g.isDefault)?.id ?? 'default')

  const kw = search.trim()
  const list = useMemo(() => (kw ? favGroups.filter((g) => g.name.includes(kw)) : favGroups), [favGroups, kw])
  const alreadyFav = favorites.some((f) => f.id === question.id)

  const confirm = () => {
    if (!picked) {
      showToast('请选择一个收藏分组')
      return
    }
    const groupName = favGroups.find((g) => g.id === picked)?.name ?? ''
    if (alreadyFav) {
      // 已收藏：仅更换分组
      setFavoriteGroup(question.id, picked)
      showToast(`已移入「${groupName}」`)
    } else {
      addToFavorites(question, picked)
      showToast(`已收藏到「${groupName}」`)
    }
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex animate-fade-in items-center justify-center bg-[#0f1b33]/45 p-6" onClick={onClose}>
      <div
        className="flex max-h-[70vh] w-[400px] animate-pop flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h3 className="text-base font-bold text-ink">收藏到分组</h3>
          <button type="button" aria-label="关闭" onClick={onClose} className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink">
            <X size={18} />
          </button>
        </div>

        <div className="px-5 pt-3.5">
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
            <input
              autoFocus
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索分组名称"
              className="block w-full rounded-lg border border-line py-2 pl-8 pr-3 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
            />
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
          <ul className="space-y-1.5">
            {list.map((g) => {
              const on = g.id === picked
              return (
                <li key={g.id}>
                  <button
                    type="button"
                    onClick={() => setPicked(g.id)}
                    className={`flex w-full items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
                      on ? 'border-primary/50 bg-primary-weak font-medium text-primary' : 'border-line bg-white text-ink hover:border-primary/40'
                    }`}
                  >
                    <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${on ? 'bg-primary-light' : 'bg-page'}`}>
                      <Folder size={14} className={on ? 'text-primary' : 'text-ink-3'} />
                    </span>
                    <span className="flex-1 truncate">{g.name}</span>
                    {on && <span className="rounded bg-primary px-1.5 py-0.5 text-[11px] text-white">已选</span>}
                  </button>
                </li>
              )
            })}
            {!list.length && <li className="py-8 text-center text-sm text-ink-3">没有匹配的分组</li>}
          </ul>
        </div>

        <div className="flex justify-end gap-2.5 border-t border-line px-5 py-3.5">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:bg-page"
          >
            取消
          </button>
          <button
            type="button"
            onClick={confirm}
            className="rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6]"
          >
            确定
          </button>
        </div>
      </div>
    </div>
  )
}
