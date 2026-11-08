/** 题目收藏页：多标签分组管理，标签可新建/重命名/关闭（二次确认），筛选嵌入标签页内部 */
import { useEffect, useMemo, useState } from 'react'
import { ListFilter, Plus, Trash2, Users, X } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { DIFFICULTIES, TYPE_LABELS, TYPE_ORDER } from '../../../constants'
import type { Difficulty, Question, QuestionType } from '../../../types'
import QuestionCard from '../PreviewTab/QuestionCard'
import AssembleModal from '../PreviewTab/AssembleModal'
import ConfirmDialog from '../../ui/ConfirmDialog'
import Dropdown from '../../ui/Dropdown'

export default function FavoritesTab() {
  const {
    favorites,
    favGroups,
    addFavGroup,
    renameFavGroup,
    removeFavGroup,
    toggleStar,
    deleteQuestion,
    updateQuestion,
    showToast,
  } = useApp()
  const [activeGroupId, setActiveGroupId] = useState('default')
  // 默认分组 id 由后端返回，首次加载后自动对齐
  useEffect(() => {
    if (!favGroups.length) return
    if (!favGroups.some((g) => g.id === activeGroupId)) {
      setActiveGroupId(favGroups.find((g) => g.isDefault)?.id ?? favGroups[0].id)
    }
  }, [favGroups, activeGroupId])
  const [typeFilter, setTypeFilter] = useState<QuestionType | 'all'>('all')
  const [diffFilter, setDiffFilter] = useState<Difficulty | 'all'>('all')
  const [checked, setChecked] = useState<string[]>([])
  const [assembling, setAssembling] = useState(false)
  // 重命名：单击标签名进入编辑态
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  // 关闭标签二次确认
  const [closingGroup, setClosingGroup] = useState<string | null>(null)

  const activeGroup = favGroups.find((g) => g.id === activeGroupId) ?? favGroups[0]
  // 当前标签页的收藏题（缺省归入 default 组）
  const groupQuestions = useMemo(
    () => favorites.filter((q) => (q.favGroupId ?? 'default') === activeGroup?.id),
    [favorites, activeGroup],
  )

  const counts = useMemo(() => {
    const map: Record<string, number> = { all: groupQuestions.length }
    for (const q of groupQuestions) map[q.type] = (map[q.type] ?? 0) + 1
    return map
  }, [groupQuestions])

  const filtered = useMemo(
    () =>
      groupQuestions.filter(
        (q) =>
          (typeFilter === 'all' || q.type === typeFilter) && (diffFilter === 'all' || q.difficulty === diffFilter),
      ),
    [groupQuestions, typeFilter, diffFilter],
  )

  const allChecked = filtered.length > 0 && filtered.every((q) => checked.includes(q.id))

  const batchDelete = async () => {
    const ids = [...checked]
    await Promise.all(ids.map((id) => deleteQuestion(id)))
    setChecked([])
  }

  // 组卷使用当前标签页全部收藏题目（快照随组卷记录保存）
  const poolOverride = useMemo(() => groupQuestions, [groupQuestions])

  const createGroup = () => {
    void addFavGroup().then((group) => {
      setActiveGroupId(group.id)
      setTypeFilter('all')
      setDiffFilter('all')
      setChecked([])
    })
  }

  const startRename = (id: string, name: string) => {
    setRenamingId(id)
    setRenameDraft(name)
  }

  const saveRename = () => {
    if (renamingId) renameFavGroup(renamingId, renameDraft)
    setRenamingId(null)
  }

  const confirmClose = () => {
    if (!closingGroup) return
    const name = favGroups.find((g) => g.id === closingGroup)?.name ?? ''
    removeFavGroup(closingGroup)
    if (activeGroupId === closingGroup) {
      setActiveGroupId(favGroups.find((g) => g.isDefault)?.id ?? favGroups[0]?.id ?? 'default')
    }
    showToast(`标签页「${name}」已关闭，组内收藏移入「默认」`)
    setClosingGroup(null)
  }

  const resetFilters = () => {
    setTypeFilter('all')
    setDiffFilter('all')
    setChecked([])
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 标签导航栏：样式与学习空间一致；默认标签固定不可重命名/关闭；加号紧跟末尾标签右下角 */}
      <div className="flex flex-wrap items-center gap-5 border-b border-line px-5">
        {favGroups.map((g) => {
          const active = activeGroup?.id === g.id
          const renaming = renamingId === g.id
          const isDefault = g.isDefault || g.id === 'default'
          return (
            <div key={g.id} className="relative shrink-0">
              {renaming ? (
                <input
                  autoFocus
                  type="text"
                  value={renameDraft}
                  maxLength={20}
                  onChange={(e) => setRenameDraft(e.target.value)}
                  onBlur={saveRename}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') saveRename()
                    if (e.key === 'Escape') setRenamingId(null)
                  }}
                  className="w-28 rounded-md border border-primary/50 px-2 py-1 text-sm text-ink outline-none focus:border-primary"
                />
              ) : (
                <button
                  type="button"
                  title={isDefault ? undefined : '双击重命名'}
                  onClick={() => {
                    if (activeGroupId !== g.id) {
                      setActiveGroupId(g.id)
                      resetFilters()
                    }
                  }}
                  onDoubleClick={() => {
                    // 仅加号新建的标签页支持双击重命名，默认标签页不可重命名
                    if (!isDefault) startRename(g.id, g.name)
                  }}
                  className={`relative flex items-center gap-1.5 pr-4 py-3 text-sm transition-colors select-none ${
                    active ? 'font-semibold text-primary' : 'text-ink-2 hover:text-primary'
                  }`}
                >
                  {g.name}
                  {active && <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-primary" />}
                </button>
              )}
              {/* 默认标签页不可关闭，其余标签带关闭按钮 */}
              {!isDefault && !renaming && (
                <button
                  type="button"
                  title="关闭标签页"
                  onClick={(e) => {
                    e.stopPropagation()
                    setClosingGroup(g.id)
                  }}
                  className="absolute right-0 top-2 rounded p-0.5 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-500"
                >
                  <X size={11} />
                </button>
              )}
            </div>
          )
        })}
        {/* 新建标签页：紧跟末尾标签的右下角，替代原最右侧独立按钮 */}
        <button
          type="button"
          onClick={createGroup}
          title="新建标签页"
          className="mb-1.5 self-end rounded p-0.5 text-ink-3 transition-colors hover:bg-page hover:text-primary"
        >
          <Plus size={15} />
        </button>
      </div>

      {/* 标签页内容：无题目时显示方框空态，样式与组卷记录空态一致 */}
      {groupQuestions.length === 0 ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="rounded-xl border border-line/70 bg-white shadow-[0_4px_16px_rgba(30,90,180,0.05)]">
            <p className="py-12 text-center text-sm text-ink-3">
              「{activeGroup?.name}」暂无收藏题目，在「Agent出题」或「题目预览」中点亮题目卡片的星标即可收藏到本标签页
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* 题型筛选胶囊：仅当标签页内有题目时显示 */}
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
                checked={allChecked}
                onChange={(e) => setChecked(e.target.checked ? filtered.map((q) => q.id) : [])}
              />
              全选
            </label>
            <button
              type="button"
              disabled={!checked.length}
              onClick={() => void batchDelete()}
              className={`flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors ${
                checked.length
                  ? 'border-red-200 bg-red-50 text-red-500 hover:bg-red-100'
                  : 'cursor-not-allowed border-line bg-page text-ink-3 opacity-60'
              }`}
            >
              <Trash2 size={12} />
              删除
            </button>
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
              已选 {checked.length} 题
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

          {/* 收藏题目列表 */}
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-8 pt-4">
            {filtered.map((q, idx) => (
              <QuestionCard
                key={q.id}
                q={q}
                index={idx + 1}
                snapshot={snapshotCtx(checked, setChecked, toggleStar, deleteQuestion, updateQuestion, showToast)}
              />
            ))}
            {!filtered.length && <div className="py-16 text-center text-sm text-ink-3">当前筛选条件下没有题目</div>}
          </div>
        </>
      )}

      {assembling && <AssembleModal onClose={() => setAssembling(false)} poolOverride={poolOverride} />}

      {/* 关闭标签页二次确认 */}
      {closingGroup && (
        <ConfirmDialog
          title="关闭标签页"
          message={`确定关闭标签页「${favGroups.find((g) => g.id === closingGroup)?.name ?? ''}」吗？组内的收藏题目将移入「默认」标签页。`}
          confirmText="确认关闭"
          onConfirm={confirmClose}
          onClose={() => setClosingGroup(null)}
        />
      )}
    </div>
  )
}

/** 收藏页的卡片操作上下文：星标切换（取消收藏）、编辑同步全局与收藏副本、删除移出收藏夹 */
function snapshotCtx(
  checked: string[],
  setChecked: (v: string[]) => void,
  toggleStar: (id: string) => Promise<void>,
  deleteQuestion: (id: string) => Promise<void>,
  updateQuestion: (q: Question) => Promise<void>,
  showToast: (msg: string) => void,
) {
  return {
    selectedIds: checked,
    toggleSelect: (id: string) =>
      setChecked(checked.includes(id) ? checked.filter((v) => v !== id) : [...checked, id]),
    updateQuestion: (q: Question) => {
      void updateQuestion(q)
    },
    deleteQuestion: (id: string) => {
      void deleteQuestion(id)
      setChecked(checked.filter((v) => v !== id))
    },
    toggleStar: (id: string) => {
      void toggleStar(id)
      setChecked(checked.filter((v) => v !== id))
      showToast('已取消收藏')
    },
  }
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
