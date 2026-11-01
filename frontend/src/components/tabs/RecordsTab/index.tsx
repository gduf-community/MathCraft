/** 组卷记录页：内部多标签（组卷记录列表 + 打开的试卷详情），样式复用题库管理/题目预览 */
import { useEffect, useMemo, useState } from 'react'
import {
  ClipboardList,
  FileText,
  Pencil,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { TYPE_LABELS, TYPE_ORDER } from '../../../constants'
import type { AssembleRecord, QuestionType } from '../../../types'
import QuestionCard from '../PreviewTab/QuestionCard'
import AssembleModal from '../PreviewTab/AssembleModal'
import ConfirmDialog from '../../ui/ConfirmDialog'

interface OpenTab {
  id: string
  name: string
}

/** 状态标签：已发布 / 未发布 */
function StatusTag({ published }: { published?: boolean }) {
  return published ? (
    <span className="inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-600">
      已发布
    </span>
  ) : (
    <span className="inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-600">
      未发布
    </span>
  )
}

export default function RecordsTab() {
  const { records: allRecords, deleteRecord, deleteRecordQuestions, showToast, openPaperId, clearOpenPaper } = useApp()
  // 发布时未勾选「保存到组卷记录」的记录仅用于学习空间展示，不进本页列表
  const records = useMemo(() => allRecords.filter((r) => r.savedToRecords !== false), [allRecords])
  // 第一个标签为组卷记录列表，固定不可关闭
  const [tabs, setTabs] = useState<OpenTab[]>([])
  const [activeTab, setActiveTab] = useState('list')
  const [checked, setChecked] = useState<string[]>([])
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [editingRecord, setEditingRecord] = useState<AssembleRecord | null>(null)

  const openRecord = (record: AssembleRecord) => {
    if (tabs.some((t) => t.id === record.id)) {
      setActiveTab(record.id)
      return
    }
    setTabs((prev) => [...prev, { id: record.id, name: record.name }])
    setActiveTab(record.id)
  }

  // 学习空间页点「查看」跨页联动：打开对应试卷标签
  useEffect(() => {
    if (!openPaperId) return
    const record = records.find((r) => r.id === openPaperId)
    clearOpenPaper()
    if (!record) {
      showToast('该试卷不存在或已被删除')
      return
    }
    if (tabs.some((t) => t.id === record.id)) {
      setActiveTab(record.id)
      return
    }
    setTabs((prev) => [...prev, { id: record.id, name: record.name }])
    setActiveTab(record.id)
  }, [openPaperId, records, tabs, clearOpenPaper, showToast])

  const closeTab = (id: string) => {
    setTabs((prev) => prev.filter((t) => t.id !== id))
    if (activeTab === id) setActiveTab('list')
  }

  const active = records.find((r) => r.id === activeTab)

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 子标签栏 */}
      <div className="flex items-center gap-5 overflow-x-auto border-b border-line px-5">
        <SubTab label="组卷记录" icon={ClipboardList} active={activeTab === 'list'} onClick={() => setActiveTab('list')} />
        {tabs.map((t) => (
          <div key={t.id} className="relative shrink-0">
            <SubTab label={t.name} icon={FileText} active={activeTab === t.id} onClick={() => setActiveTab(t.id)} />
            <button
              type="button"
              title="关闭标签页"
              onClick={(e) => {
                e.stopPropagation()
                closeTab(t.id)
              }}
              className="absolute right-0 top-1.5 rounded p-0.5 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-500"
            >
              <X size={11} />
            </button>
          </div>
        ))}
      </div>

      {activeTab === 'list' ? (
        <RecordList
          records={records}
          checked={checked}
          setChecked={setChecked}
          onOpen={openRecord}
          onDelete={(id) => {
            setDeleting(id)
            setConfirmDelete(true)
          }}
          onEdit={(r) => setEditingRecord(r)}
        />
      ) : active ? (
        <PaperDetail record={active} onDeleteQuestions={(ids) => deleteRecordQuestions(active.id, ids)} />
      ) : null}

      {editingRecord && (
        <AssembleModal
          editingRecord={editingRecord}
          onClose={() => setEditingRecord(null)}
        />
      )}
      {confirmDelete && deleting && (
        <ConfirmDialog
          title="删除组卷记录"
          message={`确定删除试卷「${records.find((r) => r.id === deleting)?.name ?? ''}」吗？删除后不可恢复。`}
          confirmText="确认删除"
          onConfirm={async () => {
            await deleteRecord(deleting)
            setChecked((prev) => prev.filter((id) => id !== deleting))
          }}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </div>
  )
}

function SubTab({
  label,
  icon: Icon,
  active,
  onClick,
}: {
  label: string
  icon: typeof ClipboardList
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative flex shrink-0 items-center gap-1.5 pr-4 py-3 text-sm transition-colors ${
        active ? 'font-semibold text-primary' : 'text-ink-2 hover:text-primary'
      }`}
    >
      <Icon size={15} />
      {label}
      {active && <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-primary" />}
    </button>
  )
}

/** 组卷记录列表 */
function RecordList({
  records,
  checked,
  setChecked,
  onOpen,
  onDelete,
  onEdit,
}: {
  records: AssembleRecord[]
  checked: string[]
  setChecked: (v: string[]) => void
  onOpen: (r: AssembleRecord) => void
  onDelete: (id: string) => void
  onEdit: (r: AssembleRecord) => void
}) {
  const allChecked = records.length > 0 && records.every((r) => checked.includes(r.id))
  const viewBtn = 'inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary-light/50 px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary-light'
  const delBtn = 'inline-flex items-center gap-1 rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs font-medium text-red-500 transition-colors hover:bg-red-100'

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-5">
      <div className="rounded-xl border border-line/70 bg-white shadow-[0_4px_16px_rgba(30,90,180,0.05)]">
        <div className="flex items-center justify-between px-5 pb-3 pt-4">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
            <input
              type="checkbox"
              className="h-4 w-4 accent-primary"
              checked={allChecked}
              onChange={(e) => setChecked(e.target.checked ? records.map((r) => r.id) : [])}
            />
            全选
          </label>
          <button
            type="button"
            disabled={!checked.length}
            onClick={() => {
              checked.forEach((id) => onDelete(id))
              setChecked([])
            }}
            className={`flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors ${
              checked.length
                ? 'border-red-200 bg-red-50 text-red-500 hover:bg-red-100'
                : 'cursor-not-allowed border-line bg-page text-ink-3 opacity-60'
            }`}
          >
            <Trash2 size={12} />
            批量删除
          </button>
        </div>

        <table className="w-full">
          <thead>
            <tr className="border-y border-line/70 bg-page/60 text-left text-xs text-ink-3">
              <th className="w-10 px-4 py-2.5" />
              <th className="px-3 py-2.5 font-normal">试卷名称</th>
              <th className="px-3 py-2.5 font-normal">创建时间</th>
              <th className="px-3 py-2.5 font-normal">状态</th>
              <th className="px-5 py-2.5 text-right font-normal">操作</th>
            </tr>
          </thead>
          <tbody>
            {records.length === 0 && (
              <tr>
                <td colSpan={5} className="py-12 text-center text-sm text-ink-3">
                  暂无组卷记录，去「Agent出题」生成题目并组卷发布吧
                </td>
              </tr>
            )}
            {records.map((r) => (
              <tr key={r.id} className="border-b border-line/50 transition-colors last:border-0 hover:bg-page/50">
                <td className="px-4 py-3.5">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-primary"
                    checked={checked.includes(r.id)}
                    onChange={(e) =>
                      setChecked(e.target.checked ? [...checked, r.id] : checked.filter((v) => v !== r.id))
                    }
                  />
                </td>
                <td className="px-3 py-3.5">
                  <div className="flex items-center gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-light">
                      <FileText size={17} className="text-primary" />
                    </span>
                    <span className="text-sm font-medium text-ink">{r.name}</span>
                  </div>
                </td>
                <td className="px-3 py-3.5 text-sm text-ink-2">{r.createdAt}</td>
                <td className="px-3 py-3.5">
                  <StatusTag published={r.published} />
                </td>
                <td className="px-5 py-3.5">
                  <div className="flex items-center justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => onEdit(r)}
                      title="编辑试卷信息并发布"
                      className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs font-medium text-amber-600 transition-colors hover:bg-amber-100"
                    >
                      <Users size={12} /> 发布
                    </button>
                    <button type="button" onClick={() => onOpen(r)} className={viewBtn}>
                      <Pencil size={12} /> 查看
                    </button>
                    <button type="button" onClick={() => onDelete(r.id)} className={delBtn}>
                      <Trash2 size={12} /> 删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** 试卷详情：筛选 + 全选/批量删除 + 题目卡片（快照上下文） */
function PaperDetail({
  record,
  onDeleteQuestions,
}: {
  record: AssembleRecord
  onDeleteQuestions: (ids: string[]) => void
}) {
  const { unfavoriteQuestion } = useApp()
  const questions = useMemo(() => record.questions ?? [], [record.questions])
  const [checked, setChecked] = useState<string[]>([])
  const [typeFilter, setTypeFilter] = useState<QuestionType | 'all'>('all')

  const counts = useMemo(() => {
    const map: Record<string, number> = { all: questions.length }
    for (const q of questions) map[q.type] = (map[q.type] ?? 0) + 1
    return map
  }, [questions])

  const filtered = useMemo(
    () =>
      questions.filter(
        (q) =>
          typeFilter === 'all' || q.type === typeFilter,
      ),
    [questions, typeFilter],
  )

  const allChecked = filtered.length > 0 && filtered.every((q) => checked.includes(q.id))
  const snapshot = {
    selectedIds: checked,
    toggleSelect: (id: string) =>
      setChecked((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id])),
    updateQuestion: () => undefined,
    deleteQuestion: (id: string) => {
      onDeleteQuestions([id])
      setChecked((prev) => prev.filter((v) => v !== id))
    },
    // 快照题目取消收藏：同步熄灭全局与快照星标
    toggleStar: (id: string) => {
      unfavoriteQuestion(id)
    },
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
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
          onClick={() => {
            onDeleteQuestions(checked)
            setChecked([])
          }}
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
          <span className="text-xs text-ink-3">创建于 {record.createdAt}</span>
          <StatusTag published={record.published} />
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-8 pt-4">
        {filtered.map((q, idx) => (
          <QuestionCard key={q.id} q={q} index={idx + 1} snapshot={snapshot} />
        ))}
        {!filtered.length && <div className="py-16 text-center text-sm text-ink-3">当前筛选条件下没有题目</div>}
      </div>
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
