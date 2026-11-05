/** 学习空间页：横向卡片行 + 查看子标签（名称编辑、成员管理、试卷联动）+ 创建/解散空间 */
import { useEffect, useMemo, useState } from 'react'
import {
  Check,
  ClipboardList,
  Clock,
  Copy,
  FileText,
  FolderOpen,
  Megaphone,
  Pencil,
  Plus,
  Save,
  Search,
  UserMinus,
  Users,
  X,
} from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import type { AssembleRecord, StudySpace } from '../../../types'
import * as api from '../../../api/backend'
import { stopPublication, resumePublication } from '../../../api/backend'
import ConfirmDialog from '../../ui/ConfirmDialog'
import ExplainView from './ExplainView'
import AnswerView from '../RecordsTab/AnswerView'

interface OpenTab {
  id: string
  name: string
  /** 打开标签时固定的组卷记录（学生看到的可能是空间发布卷，不在其组卷记录内） */
  record?: AssembleRecord
}

/** 空间发布卷 → 组卷记录视图模型（题目由作答/讲解接口按需拉取） */
function spacePaperToRecord(p: api.ApiSpacePaper, spaceName: string): AssembleRecord {
  return {
    id: p.id,
    name: p.name,
    createdAt: api.formatDateTime(p.created_at),
    questionCount: p.question_count,
    totalScore: p.total_score,
    spaces: [spaceName],
    published: p.status === 'published',
    questions: [],
    examWindow: p.exam_window
      ? { start: api.toLocalInput(p.exam_window.start), end: api.toLocalInput(p.exam_window.end) }
      : null,
    submittedCount: p.submitted_count,
    stopped: p.stopped,
    answered: p.answered,
    allowReview: p.allow_review,
    allowRetake: p.allow_retake,
    lastUrgeAt: p.last_urge_at ?? null,
  }
}

/** 催交 24 小时冷却剩余小时数；null 表示不在冷却期 */
function urgeCooldownHours(lastUrgeAt: string | null | undefined): number | null {
  if (!lastUrgeAt) return null
  const elapsed = Date.now() - new Date(lastUrgeAt).getTime()
  const remain = 24 * 3600 * 1000 - elapsed
  if (remain <= 0) return null
  return Math.ceil(remain / 3600000)
}

interface RemainInfo {
  label: string
  /** 剩余数值（天/小时/分钟），非剩余状态为空 */
  num?: string
  unit?: string
  /** 终态（停止/已结束）时信息条整体置灰 */
  muted?: boolean
}

/** 剩余作答时间：按 结束时间 − 当前时间 计算；未开始不倒计时，不足一天按小时/分钟显示 */
function remainInfo(record: AssembleRecord): RemainInfo {
  if (record.stopped) return { label: '已停止作答', muted: true }
  if (!record.examWindow) return { label: '不限时间' }
  const start = new Date(record.examWindow.start).getTime()
  const end = new Date(record.examWindow.end).getTime()
  const now = Date.now()
  // 作答窗口尚未开始：直接显示未开始，不提前倒计时
  if (now < start) return { label: '未开始' }
  if (now >= end) return { label: '已结束', muted: true }
  const diff = end - now
  const days = Math.floor(diff / 86400000)
  if (days >= 1) return { label: '剩余', num: String(days), unit: '天' }
  const hours = Math.floor(diff / 3600000)
  if (hours >= 1) return { label: '剩余', num: String(hours), unit: '小时' }
  return { label: '剩余', num: String(Math.max(1, Math.floor(diff / 60000))), unit: '分钟' }
}

export default function SpaceTab() {
  const {
    spaces,
    role,
    joinSpaceByCode,
    leaveSpace,
    dissolveSpace,
    records,
    pendingSpacePaper,
    clearPendingSpacePaper,
    showToast,
  } = useApp()
  // 第一个标签为空间列表，固定不可关闭；查看空间时打开动态标签
  const [tabs, setTabs] = useState<OpenTab[]>([])
  const [activeTab, setActiveTab] = useState('list')
  const [createOpen, setCreateOpen] = useState(false)
  const [leaving, setLeaving] = useState<StudySpace | null>(null)
  const [joinCode, setJoinCode] = useState('')
  const [joinError, setJoinError] = useState(false)

  const openSpace = (space: StudySpace) => {
    if (tabs.some((t) => t.id === space.id)) {
      setActiveTab(space.id)
      return
    }
    setTabs((prev) => [...prev, { id: space.id, name: space.name }])
    setActiveTab(space.id)
  }

  /** 教师：讲解题目，新开标签页（左侧题目 + 右侧导航与作答分布） */
  const openExplain = (record: AssembleRecord) => {
    const tabId = `explain-${record.id}`
    if (tabs.some((t) => t.id === tabId)) {
      setActiveTab(tabId)
      return
    }
    setTabs((prev) => [...prev, { id: tabId, name: record.name, record }])
    setActiveTab(tabId)
  }

  /** 学生：作答空间内发布的试卷，新开标签页（答题 + AI 批卷）；已过作答时间禁止进入 */
  const openAnswer = (record: AssembleRecord) => {
    if (remainInfo(record).label === '已结束') {
      showToast('已过作答时间')
      return
    }
    const tabId = `answer-${record.id}`
    if (tabs.some((t) => t.id === tabId)) {
      setActiveTab(tabId)
      return
    }
    setTabs((prev) => [...prev, { id: tabId, name: record.name, record }])
    setActiveTab(tabId)
  }

  const closeTab = (id: string) => {
    setTabs((prev) => prev.filter((t) => t.id !== id))
    if (activeTab === id) setActiveTab('list')
  }

  // 通知「立即查看」：打开对应空间并直接进入该试卷的作答标签页
  useEffect(() => {
    if (!pendingSpacePaper) return
    const { spaceId, paperId } = pendingSpacePaper
    clearPendingSpacePaper()
    const space = spaces.find((s) => s.id === spaceId)
    if (!space) {
      showToast('未找到该学习空间，可能已退出或被解散')
      return
    }
    let cancelled = false
    void api
      .listSpacePapers(spaceId)
      .then((rows) => {
        if (cancelled) return
        const p = rows.find((r) => r.id === paperId)
        if (!p) {
          showToast('该试卷不存在或已被删除')
          return
        }
        const record = spacePaperToRecord(p, space.name)
        const tabId = `answer-${paperId}`
        setTabs((prev) => {
          let next = prev.some((t) => t.id === spaceId) ? prev : [...prev, { id: spaceId, name: space.name }]
          if (!next.some((t) => t.id === tabId)) next = [...next, { id: tabId, name: record.name, record }]
          return next
        })
        setActiveTab(tabId)
      })
      .catch(() => showToast('打开试卷失败'))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingSpacePaper])

  const activeTabObj = tabs.find((t) => t.id === activeTab)
  const active = spaces.find((s) => s.id === activeTab)
  const explainRecord = activeTabObj?.record

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 子标签栏：左侧标签 + 右侧创建按钮同行 */}
      <div className="flex items-center gap-5 overflow-x-auto border-b border-line px-5">
        <button
          type="button"
          onClick={() => setActiveTab('list')}
          className={`relative flex shrink-0 items-center gap-1.5 py-3 text-sm transition-colors ${
            activeTab === 'list' ? 'font-semibold text-primary' : 'text-ink-2 hover:text-primary'
          }`}
        >
          <ClipboardList size={15} />
          学习空间
          {activeTab === 'list' && <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-primary" />}
        </button>
        {tabs.map((t) => (
          <div key={t.id} className="relative shrink-0">
            <button
              type="button"
              onClick={() => setActiveTab(t.id)}
              className={`relative flex items-center gap-1.5 pr-4 py-3 text-sm transition-colors ${
                activeTab === t.id ? 'font-semibold text-primary' : 'text-ink-2 hover:text-primary'
              }`}
            >
              <FolderOpen size={15} />
              {t.name}
              {activeTab === t.id && <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-primary" />}
            </button>
            <button
              type="button"
              title="关闭标签页"
              onClick={(e) => {
                e.stopPropagation()
                closeTab(t.id)
              }}
              className="absolute right-0 top-2 rounded p-0.5 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-500"
            >
              <X size={11} />
            </button>
          </div>
        ))}
        {role === 'student' ? (
          <>
            <input
              type="text"
              value={joinCode}
              onChange={(e) => {
                setJoinCode(e.target.value)
                setJoinError(false)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  void joinSpaceByCode(joinCode).then((space) => {
                    if (space) {
                      setJoinCode('')
                      openSpace(space)
                    } else {
                      setJoinError(true)
                    }
                  })
                }
              }}
              placeholder="输入空间编号"
              maxLength={20}
              className={`ml-auto w-44 shrink-0 rounded-lg border bg-white px-3 py-1.5 text-xs text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary ${
                joinError ? 'border-red-300' : 'border-line'
              }`}
            />
            <button
              type="button"
              onClick={() => {
                void joinSpaceByCode(joinCode).then((space) => {
                  if (space) {
                    setJoinCode('')
                    openSpace(space)
                  } else {
                    setJoinError(true)
                  }
                })
              }}
              className="flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3.5 py-1.5 text-xs font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6]"
            >
              <Plus size={14} />
              加入学习空间
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="ml-auto flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3.5 py-1.5 text-xs font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6]"
          >
            <Plus size={14} />
            创建学习空间
          </button>
        )}
      </div>

      {activeTab.startsWith('answer-') && explainRecord ? (
        <AnswerView key={explainRecord.id} record={explainRecord} />
      ) : activeTab.startsWith('explain-') && explainRecord ? (
        <ExplainView record={explainRecord} space={active ?? spaces[0]} />
      ) : activeTab === 'list' ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="grid grid-cols-4 gap-4">
            {spaces.map((s) => (
              <SpaceCard
                key={s.id}
                space={s}
                isStudent={role === 'student'}
                onOpen={openSpace}
                onLeave={() => setLeaving(s)}
              />
            ))}
          </div>
        </div>
      ) : active ? (
        <SpaceDetail space={active} records={records} onExplain={openExplain} onAnswer={openAnswer} />
      ) : null}

      {createOpen && (
        <CreateSpaceModal
          onClose={() => setCreateOpen(false)}
          onCreate={(space) => {
            setTabs((prev) => [...prev, { id: space.id, name: space.name }])
            setActiveTab(space.id)
          }}
        />
      )}

      {leaving &&
        (role === 'student' ? (
          <ConfirmDialog
            title="退出学习空间"
            message={`确定退出「${leaving.name}」吗？退出后需要通过空间编号重新加入。`}
            confirmText="确认退出"
            onConfirm={async () => {
              leaveSpace(leaving.id)
              closeTab(leaving.id)
            }}
            onClose={() => setLeaving(null)}
          />
        ) : (
          <ConfirmDialog
            title="解散学习空间"
            message={`确定解散「${leaving.name}」吗？空间内的成员将全部移出，已发布的试卷记录仍会保留。`}
            confirmText="确认解散"
            onConfirm={async () => {
              dissolveSpace(leaving.id)
              closeTab(leaving.id)
            }}
            onClose={() => setLeaving(null)}
          />
        ))}
    </div>
  )
}

/** 空间卡片：名称、可点击复制的编号、人数、退出（学生）/解散（教师）与查看 */
function SpaceCard({
  space,
  isStudent,
  onOpen,
  onLeave,
}: {
  space: StudySpace
  isStudent: boolean
  onOpen: (s: StudySpace) => void
  onLeave: () => void
}) {
  const { showToast } = useApp()
  const [copied, setCopied] = useState(false)

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(space.code)
    } catch {
      /* 剪贴板不可用时忽略，提示仍展示编号 */
    }
    setCopied(true)
    showToast(`空间编号 ${space.code} 已复制`)
    window.setTimeout(() => setCopied(false), 1200)
  }

  return (
    <div className="flex flex-col rounded-xl border border-line/70 bg-white p-4 shadow-[0_4px_16px_rgba(30,90,180,0.05)] transition-shadow hover:shadow-[0_6px_20px_rgba(30,90,180,0.10)]">
      <div className="flex items-center gap-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-light">
          <Users size={17} className="text-primary" />
        </span>
        <span className="truncate text-sm font-semibold text-ink" title={space.name}>
          {space.name}
        </span>
      </div>
      <div className="mt-3 space-y-1.5 text-xs text-ink-3">
        <p className="flex items-center gap-1">
          编号：
          <button
            type="button"
            title="点击复制空间编号"
            onClick={() => void copyCode()}
            className="inline-flex items-center gap-1 rounded px-1 font-mono text-ink-2 transition-colors hover:bg-primary-light hover:text-primary"
          >
            {space.code}
            {copied ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
          </button>
        </p>
        <p className="flex items-center gap-1" title={`学生 ${Math.max(0, space.memberCount - 1)} 人（不含创建者）`}>
          <Users size={12} />
          {Math.max(0, space.memberCount - 1)} / {space.capacity}
        </p>
      </div>
      <div className="mt-3 flex justify-end gap-2 border-t border-line/60 pt-2.5">
        <button
          type="button"
          onClick={onLeave}
          className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs font-medium text-red-500 transition-colors hover:bg-red-100"
        >
          <X size={12} /> {isStudent ? '退出' : '解散'}
        </button>
        <button
          type="button"
          onClick={() => onOpen(space)}
          className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary-light/50 px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary-light"
        >
          查看
        </button>
      </div>
    </div>
  )
}

/** 空间详情：可编辑名称、成员管理、发布试卷条目（时间/交卷/停止/作答情况） */
function SpaceDetail({
  space,
  records,
  onExplain,
  onAnswer,
}: {
  space: StudySpace
  records: AssembleRecord[]
  onExplain: (r: AssembleRecord) => void
  onAnswer: (r: AssembleRecord) => void
}) {
  const { role, spaces, showToast, updateRecord, deleteRecord, removeSpaceMember, renameSpace } = useApp()
  const isStudent = role === 'student'
  // 学生人数：不含创建者（老师）
  const studentCount = Math.max(0, space.memberCount - 1)
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState(space.name)
  const [memberModal, setMemberModal] = useState(false)
  const [deletingPaper, setDeletingPaper] = useState<AssembleRecord | null>(null)

  // 组卷记录按账号隔离：学生看空间发布卷走独立接口，教师看自己创建的试卷（来自组卷记录）
  const [spacePapers, setSpacePapers] = useState<AssembleRecord[]>([])
  useEffect(() => {
    if (!isStudent) return
    let cancelled = false
    api
      .listSpacePapers(space.id)
      .then((rows) => {
        if (!cancelled) setSpacePapers(rows.map((p) => spacePaperToRecord(p, space.name)))
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [isStudent, space.id, space.name])

  const papers = useMemo(
    () => (isStudent ? spacePapers : records.filter((r) => r.published && r.spaces.includes(space.name))),
    [isStudent, spacePapers, records, space.name],
  )

  const startEdit = () => {
    setNameDraft(space.name)
    setEditingName(true)
  }

  const saveName = () => {
    if (!nameDraft.trim()) {
      showToast('空间名称不能为空')
      return
    }
    renameSpace(space.id, nameDraft.trim())
    setEditingName(false)
    showToast('空间名称已更新')
  }

  /** 催交：24 小时冷却，成功后本地同步最近催交时间 */
  const [urgeAtMap, setUrgeAtMap] = useState<Record<string, string>>({})
  const urge = (record: AssembleRecord) => {
    const spaceId = spaces.find((s) => s.name === record.spaces[0])?.id ?? space.id
    void api
      .urgePaper(record.id, spaceId)
      .then(() => {
        const nowIso = new Date().toISOString()
        setUrgeAtMap((prev) => ({ ...prev, [record.id]: nowIso }))
        showToast('已催促学生提交试卷')
      })
      .catch((err) => showToast(err instanceof Error ? err.message : '催交失败'))
  }

  const lastUrgeOf = (record: AssembleRecord) => urgeAtMap[record.id] ?? record.lastUrgeAt ?? null

  /** 停止 / 恢复作答切换 */
  const toggleStop = (record: AssembleRecord) => {
    const next = !record.stopped
    const target = spaces.find((s) => record.spaces.includes(s.name))
    if (!target) {
      showToast('找不到试卷所属空间')
      return
    }
    void (next ? stopPublication(record.id, target.id) : resumePublication(record.id, target.id))
      .then(() => updateRecord({ ...record, stopped: next }))
      .catch((err) => showToast(err instanceof Error ? err.message : '操作失败'))
  }

  const deletePaper = (record: AssembleRecord) => {
    // 空间侧删除为整卷删除（组卷记录一并移除）
    void deleteRecord(record.id, { withPaper: true })
    showToast(`已删除试卷「${record.name}」`)
  }

  const iconBtn = 'inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors'

  return (
    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
      <section className="grid grid-cols-3 gap-3">
        <div className="rounded-xl border border-line bg-white p-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-ink-3">空间名称</p>
            {editingName ? (
              <button type="button" onClick={saveName} title="保存" className="rounded p-0.5 text-primary transition-colors hover:bg-primary-light">
                <Save size={13} />
              </button>
            ) : (
              // 学生无编辑权限，不显示编辑按钮
              !isStudent && (
                <button type="button" onClick={startEdit} title="编辑" className="rounded p-0.5 text-ink-3 transition-colors hover:bg-primary-light hover:text-primary">
                  <Pencil size={13} />
                </button>
              )
            )}
          </div>
          {editingName ? (
            <input
              type="text"
              value={nameDraft}
              maxLength={40}
              onChange={(e) => setNameDraft(e.target.value)}
              className="mt-1 block w-full rounded-lg border border-line px-2 py-1.5 text-sm font-semibold text-ink outline-none focus:border-primary"
            />
          ) : (
            <p className="mt-1 truncate text-sm font-semibold text-ink">{space.name}</p>
          )}
        </div>
        <div className="rounded-xl border border-line bg-white p-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-ink-3">学生人数</p>
            <button
              type="button"
              onClick={() => setMemberModal(true)}
              className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary-light/50 px-2 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-primary-light"
            >
              查看
            </button>
          </div>
          <p className="mt-1 text-sm font-semibold text-ink" title={`不含创建者（${space.creator}）`}>
            {studentCount} / {space.capacity}
          </p>
        </div>
        <div className="rounded-xl border border-line bg-white p-4">
          <p className="text-xs text-ink-3">空间编号（点击复制）</p>
          <button
            type="button"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(space.code)
              } catch {
                /* 忽略 */
              }
              showToast(`空间编号 ${space.code} 已复制`)
            }}
            className="mt-1 inline-flex items-center gap-1.5 rounded px-1 font-mono text-sm font-semibold text-ink transition-colors hover:bg-primary-light hover:text-primary"
          >
            {space.code}
            <Copy size={13} className="text-ink-3" />
          </button>
        </div>
      </section>

      <section>
        <h3 className="mb-3 flex items-center gap-1.5 text-sm font-bold text-ink">
          <FolderOpen size={15} className="text-primary" />
          发布到本空间的试卷（{papers.length}）
        </h3>
        {papers.length === 0 ? (
          <div className="rounded-xl border border-dashed border-line bg-page px-4 py-8 text-center text-sm text-ink-3">
            暂无发布的试卷，可在组卷发布时选择本空间
          </div>
        ) : (
          <ul className="space-y-2.5">
            {papers.map((r) => {
              const started = r.examWindow ? new Date(r.examWindow.start).toLocaleString('zh-CN', { hour12: false }) : null
              const ended = r.examWindow ? new Date(r.examWindow.end).toLocaleString('zh-CN', { hour12: false }) : null
              const stopped = !!r.stopped
              const remain = remainInfo(r)
              // 作答进度：已交卷人数 / 空间学生数
              const pct = studentCount > 0 ? Math.min(100, Math.round(((r.submittedCount ?? 0) / studentCount) * 100)) : 0
              return (
                <li
                  key={r.id}
                  className="group relative overflow-hidden rounded-xl border border-line bg-white p-4 pl-5 transition-colors hover:bg-primary-light/15"
                >
                  {/* 悬停左侧蓝色竖条 */}
                  <span className="absolute inset-y-0 left-0 w-1 rounded-r bg-primary opacity-0 transition-opacity group-hover:opacity-100" />
                  {/* 三列网格：图标与名称 | 剩余/作答与进度条 | 操作按钮 */}
                  <div className="grid grid-cols-[minmax(0,1.1fr)_minmax(0,1.2fr)_auto] items-center gap-6">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary-light">
                        <FileText size={18} className="text-primary" />
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-ink" title={r.name}>
                          {r.name}
                        </p>
                        <p className="mt-0.5 truncate text-xs text-ink-3">
                          {r.examWindow ? `开始 ${started} · 结束 ${ended}` : '不限时间'}
                        </p>
                      </div>
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-6 whitespace-nowrap">
                        <span className="flex items-baseline gap-1">
                          <Clock size={14} className="translate-y-0.5 text-ink-3" />
                          <span className={`text-sm font-medium ${remain.muted ? 'text-ink-3' : 'text-ink-2'}`}>{remain.label}</span>
                          {remain.num && <span className="text-xl font-bold leading-none text-primary">{remain.num}</span>}
                          {remain.unit && <span className="text-sm font-medium text-ink">{remain.unit}</span>}
                        </span>
                        <span className="flex items-baseline gap-1">
                          <Pencil size={13} className="translate-y-0.5 text-ink-3" />
                          <span className="text-sm font-medium text-ink-2">作答</span>
                          <span className="text-xl font-bold leading-none text-ink">{r.submittedCount ?? 0}</span>
                          <span className="text-sm text-ink-2">/ {studentCount}</span>
                        </span>
                      </div>
                      <div className="mt-2 flex items-center gap-2">
                        <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-page">
                          <div
                            className="h-full rounded-full bg-primary transition-[width] duration-300"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="w-8 shrink-0 text-right text-xs text-ink-3">{pct}%</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      {isStudent ? (
                        // 学生：只保留作答入口
                        <button
                          type="button"
                          onClick={() => onAnswer(r)}
                          className={`${iconBtn} border-emerald-200 bg-emerald-50 text-emerald-600 hover:bg-emerald-100`}
                        >
                          作答
                        </button>
                      ) : (
                        <>
                          {(() => {
                            const coolHours = urgeCooldownHours(lastUrgeOf(r))
                            return (
                              <button
                                type="button"
                                title={coolHours ? `还有 ${coolHours} 小时可再次点击` : '催促未交卷的学生提交'}
                                onClick={() => {
                                  // 冷却期内不禁用按钮，点击仅提示剩余等待时间
                                  if (coolHours) {
                                    showToast(`还有 ${coolHours} 小时可再次点击`)
                                    return
                                  }
                                  urge(r)
                                }}
                                className={`${iconBtn} border-violet-200 bg-violet-50 text-violet-600 hover:bg-violet-100`}
                              >
                                <Megaphone size={12} />
                                催交
                              </button>
                            )
                          })()}
                          <button
                            type="button"
                            onClick={() => toggleStop(r)}
                            className={`${iconBtn} ${
                              stopped
                                ? 'border-emerald-200 bg-emerald-50 text-emerald-600 hover:bg-emerald-100'
                                : 'border-amber-200 bg-amber-50 text-amber-600 hover:bg-amber-100'
                            }`}
                          >
                            {stopped ? '恢复作答' : '停止作答'}
                          </button>
                          <button
                            type="button"
                            onClick={() => onExplain(r)}
                            className={`${iconBtn} border border-primary/30 bg-primary-light/50 text-primary hover:bg-primary-light`}
                          >
                            讲解题目
                          </button>
                          <button
                            type="button"
                            disabled={!stopped}
                            title={stopped ? undefined : '请先停止作答，才能删除试卷'}
                            onClick={() => setDeletingPaper(r)}
                            className={`${iconBtn} border-red-200 bg-red-50 text-red-500 hover:bg-red-100 ${
                              stopped ? '' : 'cursor-not-allowed opacity-50'
                            }`}
                          >
                            删除
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {/* 成员查看弹窗 */}
      {memberModal && (
        <MemberListModal
          title="空间成员"
          space={space}
          onClose={() => setMemberModal(false)}
          onRemove={isStudent ? undefined : (name) => removeSpaceMember(space.id, name)}
        />
      )}

      {/* 删除试卷确认 */}
      {deletingPaper && (
        <ConfirmDialog
          title="删除试卷"
          message={`确定从本空间删除试卷「${deletingPaper.name}」吗？该组卷记录将一并删除。`}
          confirmText="确认删除"
          onConfirm={() => deletePaper(deletingPaper)}
          onClose={() => setDeletingPaper(null)}
        />
      )}
    </div>
  )
}

/** 成员查看弹窗：搜索 + 滚动名单；教师可移出普通成员，创建者受保护 */
function MemberListModal({
  title,
  space,
  onClose,
  onRemove,
}: {
  title: string
  space: StudySpace
  onClose: () => void
  onRemove?: (name: string) => void
}) {
  const [query, setQuery] = useState('')
  const list = useMemo(
    () => space.members.filter((m) => m.includes(query.trim())),
    [space.members, query],
  )
  return (
    <div className="fixed inset-0 z-50 flex animate-fade-in items-center justify-center bg-[#0f1b33]/45 p-4" onClick={onClose}>
      <div
        className="flex max-h-[70vh] w-[400px] animate-pop flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h3 className="text-base font-bold text-ink">{title}</h3>
          <button type="button" onClick={onClose} className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink">
            <X size={18} />
          </button>
        </div>
        <div className="px-5 pt-3.5">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索成员姓名"
              className="block w-full rounded-lg border border-line py-2 pl-8 pr-3 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
            />
          </div>
          <p className="mt-2 text-xs text-ink-3">
            共 {space.members.length} 人 · 学生 {Math.max(0, space.memberCount - 1)} 人（不含创建者）
          </p>
        </div>
        <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto px-5 py-3">
          {list.map((m) => {
            const isCreator = m === space.creator
            return (
              <li key={m} className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-page">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-light text-sm font-semibold text-primary">
                  {m.slice(0, 1)}
                </span>
                <span className="flex-1 truncate text-sm text-ink">{m}</span>
                {isCreator && (
                  <span className="rounded bg-primary-light px-1.5 py-0.5 text-[11px] font-medium text-primary">创建者</span>
                )}
                {onRemove && !isCreator && (
                  <button
                    type="button"
                    onClick={() => onRemove(m)}
                    title="移出空间"
                    className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-[11px] font-medium text-red-500 transition-colors hover:bg-red-100"
                  >
                    <UserMinus size={11} /> 移出
                  </button>
                )}
              </li>
            )
          })}
          {!list.length && <li className="py-8 text-center text-sm text-ink-3">没有匹配的成员</li>}
        </ul>
      </div>
    </div>
  )
}

/** 创建学习空间弹窗：名称 + 人数上限，编号自动生成；创建后展示成功态与可复制的编号 */
function CreateSpaceModal({
  onClose,
  onCreate: _onCreate,
}: {
  onClose: () => void
  onCreate: (space: StudySpace) => void
}) {
  const year = new Date().getFullYear()
  const { showToast, createSpace } = useApp()
  const [name, setName] = useState('')
  const [capacity, setCapacity] = useState('50')
  const [created, setCreated] = useState<StudySpace | null>(null)
  const [copied, setCopied] = useState(false)

  const submit = () => {
    if (!name.trim()) {
      showToast('请输入空间名称')
      return
    }
    const cap = Math.max(1, Math.min(500, Number(capacity) || 50))
    void createSpace(name.trim(), cap)
      .then((space) => setCreated(space))
      .catch((err) => showToast(err instanceof Error ? err.message : '创建失败'))
  }

  const copyCode = async () => {
    if (!created) return
    try {
      await navigator.clipboard.writeText(created.code)
    } catch {
      /* 忽略 */
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1200)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={onClose}>
      <div
        className="flex max-h-[80vh] w-[460px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {created ? (
          <>
            <div className="flex flex-col items-center px-6 py-8">
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 text-emerald-500">
                <Check size={28} />
              </span>
              <h3 className="mt-3 text-lg font-bold text-ink">创建成功</h3>
              <p className="mt-1.5 text-sm text-ink-2">学习空间「{created.name}」已创建</p>
              <button
                type="button"
                onClick={() => void copyCode()}
                className="mt-5 flex w-full items-center justify-between rounded-xl border border-line bg-page px-4 py-3 transition-colors hover:border-primary/50"
                title="点击复制空间编号"
              >
                <span className="font-mono text-base font-semibold tracking-wide text-ink">{created.code}</span>
                <span className="inline-flex items-center gap-1 text-xs text-primary">
                  {copied ? <Check size={13} /> : <Copy size={13} />}
                  {copied ? '已复制' : '复制编号'}
                </span>
              </button>
              <p className="mt-2 self-start text-xs text-ink-3">请把编号分享给需要加入该空间的同学</p>
            </div>
            <div className="flex justify-end border-t border-line px-5 py-3.5">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6]"
              >
                完成
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <div className="flex items-center gap-2">
                <Plus size={18} className="text-primary" />
                <h3 className="text-base font-bold text-ink">创建学习空间</h3>
              </div>
              <button type="button" onClick={onClose} className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink">
                <X size={18} />
              </button>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
              <label className="block">
                <span className="mb-1 block text-xs text-ink-3">空间名称</span>
                <input
                  type="text"
                  value={name}
                  maxLength={40}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="如：计科2班"
                  className="block w-full rounded-lg border border-line px-3 py-2 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-ink-3">空间编号（创建后自动生成）</span>
                <input
                  type="text"
                  value={`SP${year}••••`}
                  readOnly
                  className="block w-full cursor-not-allowed rounded-lg border border-line bg-page px-3 py-2 text-sm text-ink-2"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-ink-3">人数上限</span>
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={capacity}
                  onChange={(e) => setCapacity(e.target.value)}
                  className="block w-full rounded-lg border border-line px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary"
                />
              </label>
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
                onClick={submit}
                className="rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6]"
              >
                创建
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
