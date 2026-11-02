import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, X } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { TYPE_LABELS, TYPE_ORDER } from '../../../constants'
import type { AssembleRecord, ExamWindow, PaperModule, Question } from '../../../types'

interface Props {
  onClose: () => void
  /** 来源覆盖：传入时组卷池使用该题目集合（如收藏页），忽略全局勾选 */
  poolOverride?: Question[]
  /** 编辑模式：传入组卷记录后，弹窗变为编辑该试卷并更新记录 */
  editingRecord?: AssembleRecord
}

/** 当前本地时间，datetime-local 格式（YYYY-MM-DDTHH:mm） */
function nowLocal(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * 组卷弹窗：
 * - 试卷名称（默认按日期生成，可修改；与组卷记录同名时自动追加（1）（2）…）
 * - 按题型模块（而非单个题目）排序，提供上移/下移
 * - 发布到学习空间（多选）与做题时间（可不限）
 * - 顶部「保存到组卷记录」复选框，默认勾选
 * - 底部「暂不发布」「发布」「取消」
 * - 传入 editingRecord 时为编辑模式：沿用记录的命名/空间/时间/题目，保存后更新记录
 */
export default function AssembleModal({ onClose, poolOverride, editingRecord }: Props) {
  const { questions, selectedIds, spaces, records, publishPaper, showToast, updateRecord } = useApp()

  // 已勾选题目参与组卷；未勾选时默认使用当前全部题目；传入 poolOverride/editingRecord 时以对应集合为准
  const pool = useMemo(
    () =>
      editingRecord
        ? editingRecord.questions ?? []
        : poolOverride
          ? poolOverride
          : selectedIds.length
            ? questions.filter((q) => selectedIds.includes(q.id))
            : questions,
    [editingRecord, poolOverride, questions, selectedIds],
  )

  const [modules, setModules] = useState<PaperModule[]>(() => {
    const byType = new Map<string, PaperModule>()
    for (const q of pool) {
      const m = byType.get(q.type) ?? { type: q.type, count: 0, totalScore: 0 }
      m.count += 1
      m.totalScore += q.score
      byType.set(q.type, m)
    }
    return TYPE_ORDER.filter((t) => byType.has(t)).map((t) => byType.get(t)!)
  })
  // 编辑模式：按空间名反查 id 作为初始勾选
  const [chosenSpaces, setChosenSpaces] = useState<string[]>(() =>
    editingRecord ? spaces.filter((s) => editingRecord.spaces.includes(s.name)).map((s) => s.id) : [],
  )
  const [saveRecord, setSaveRecord] = useState(true)
  const [paperName, setPaperName] = useState(
    () => editingRecord?.name ?? `试卷_${new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })}`,
  )
  // 做题时间：新建默认需要规定；编辑模式按记录是否有时间窗口初始化
  const [noTimeLimit, setNoTimeLimit] = useState(() => (editingRecord ? !editingRecord.examWindow : false))
  const [timeStart, setTimeStart] = useState(() => editingRecord?.examWindow?.start ?? '')
  const [timeEnd, setTimeEnd] = useState(() => editingRecord?.examWindow?.end ?? '')

  const move = (idx: number, dir: -1 | 1) => {
    setModules((prev) => {
      const next = [...prev]
      const target = idx + dir
      if (target < 0 || target >= next.length) return prev
      ;[next[idx], next[target]] = [next[target], next[idx]]
      return next
    })
  }

  const totalCount = modules.reduce((s, m) => s + m.count, 0)
  const totalScore = modules.reduce((s, m) => s + m.totalScore, 0)

  /** 试卷名与组卷记录查重：同名自动追加（1）（2）…；编辑模式排除自身 */
  const uniqueName = (base: string): string => {
    const taken = new Set(records.filter((r) => r.id !== editingRecord?.id).map((r) => r.name))
    if (!taken.has(base)) return base
    let i = 1
    while (taken.has(`${base}（${i}）`)) i += 1
    return `${base}（${i}）`
  }

  const validateTime = (): ExamWindow | null | undefined => {
    if (noTimeLimit) return null
    if (!timeStart || !timeEnd) {
      showToast('请选择做题的开始与结束时间，或勾选「不规定做题时间」')
      return undefined
    }
    if (timeStart < nowLocal()) {
      showToast('开始时间不能早于当前时间')
      return undefined
    }
    if (timeEnd <= timeStart) {
      showToast('结束时间必须晚于开始时间')
      return undefined
    }
    return { start: timeStart, end: timeEnd }
  }

  const publish = async () => {
    const examWindow = validateTime()
    if (examWindow === undefined) return
    const name = uniqueName(paperName.trim() || `试卷_${new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })}`)
    // 编辑模式：更新已有记录
    if (editingRecord) {
      if (!chosenSpaces.length) {
        showToast('请至少选择一个学习空间')
        return
      }
      const spaceNames = chosenSpaces.map((id) => spaces.find((s) => s.id === id)?.name ?? '').filter(Boolean)
      updateRecord({
        ...editingRecord,
        name,
        spaces: spaceNames,
        examWindow,
        published: true,
        questions: pool,
        stopped: false,
      })
      showToast('试卷已更新并发布')
      onClose()
      return
    }
    const ok = await publishPaper(
      modules,
      chosenSpaces,
      saveRecord,
      name,
      true,
      pool,
      examWindow,
    )
    if (ok) onClose()
  }

  const saveDraft = () => {
    // 暂不发布：做题时间不必填
    const examWindow: ExamWindow | null = noTimeLimit ? null : timeStart && timeEnd ? { start: timeStart, end: timeEnd } : null
    const name = uniqueName(paperName.trim() || `试卷_${new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })}`)
    if (editingRecord) {
      updateRecord({
        ...editingRecord,
        name,
        spaces: chosenSpaces.map((id) => spaces.find((s) => s.id === id)?.name ?? '').filter(Boolean),
        examWindow,
        published: false,
        questions: pool,
      })
      showToast('试卷已暂存为草稿')
      onClose()
      return
    }
    void publishPaper(modules, [], false, name, false, pool, examWindow)
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-40 flex animate-fade-in items-center justify-center bg-[#0f1b33]/45 p-6"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-[560px] animate-pop flex-col rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <h3 className="text-base font-bold text-ink">{editingRecord ? '编辑试卷' : '组卷发布'}</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
          <section>
            <h4 className="mb-2 text-sm font-bold text-ink">试卷名称</h4>
            <input
              type="text"
              value={paperName}
              maxLength={40}
              onChange={(e) => setPaperName(e.target.value)}
              placeholder="请输入试卷名称"
              className="block w-full rounded-lg border border-line px-3 py-2.5 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
            />
          </section>

          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={saveRecord}
              onChange={(e) => setSaveRecord(e.target.checked)}
              className="h-4 w-4 accent-primary"
            />
            保存到组卷记录
          </label>

          <section>
            <h4 className="mb-2 text-sm font-bold text-ink">
              题型模块排序 <span className="ml-1 text-xs font-normal text-ink-3">（按模块整体调整顺序）</span>
            </h4>
            <ul className="divide-y divide-line/70 rounded-lg border border-line">
              {modules.map((m, i) => (
                <li key={m.type} className="flex items-center gap-3 px-4 py-3">
                  <span className="rounded bg-primary-light px-2 py-0.5 text-xs font-medium text-primary">
                    {TYPE_LABELS[m.type]}
                  </span>
                  <span className="flex-1 text-sm text-ink-2">
                    {m.count} 题 · 共 {m.totalScore} 分
                  </span>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      title="上移"
                      disabled={i === 0}
                      onClick={() => move(i, -1)}
                      className="rounded-md border border-line p-1 text-ink-2 transition-colors hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      <ArrowUp size={14} />
                    </button>
                    <button
                      type="button"
                      title="下移"
                      disabled={i === modules.length - 1}
                      onClick={() => move(i, 1)}
                      className="rounded-md border border-line p-1 text-ink-2 transition-colors hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      <ArrowDown size={14} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h4 className="mb-2 text-sm font-bold text-ink">
              发布到学习空间 <span className="ml-1 text-xs font-normal text-ink-3">（可多选）</span>
            </h4>
            <div className="grid grid-cols-2 gap-2.5">
              {spaces.map((s) => {
                const on = chosenSpaces.includes(s.id)
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() =>
                      setChosenSpaces((prev) => (on ? prev.filter((v) => v !== s.id) : [...prev, s.id]))
                    }
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm transition-colors ${
                      on
                        ? 'border-primary bg-primary-light font-medium text-primary'
                        : 'border-line bg-white text-ink-2 hover:border-primary/50'
                    }`}
                  >
                    <span
                      className={`flex h-4 w-4 items-center justify-center rounded-[4px] border text-[10px] text-white ${
                        on ? 'border-primary bg-primary' : 'border-ink-3/60 bg-white'
                      }`}
                    >
                      {on ? '✓' : ''}
                    </span>
                    {s.name}
                  </button>
                )
              })}
            </div>
          </section>
          {/* 做题时间 */}
          <section>
            <h4 className="mb-2 text-sm font-bold text-ink">
              做题时间 <span className="ml-1 text-xs font-normal text-ink-3">（可选，暂不发布时不必填写）</span>
            </h4>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={noTimeLimit}
                onChange={(e) => setNoTimeLimit(e.target.checked)}
                className="h-4 w-4 accent-primary"
              />
              不规定做题时间
            </label>
            {!noTimeLimit && (
              <div className="mt-2.5 grid grid-cols-2 gap-2.5">
                <label className="block">
                  <span className="mb-1 block text-xs text-ink-3">开始时间</span>
                  <input
                    type="datetime-local"
                    min={nowLocal()}
                    value={timeStart}
                    onChange={(e) => {
                      const v = e.target.value
                      if (v && v < nowLocal()) {
                        showToast('开始时间不能早于当前时间')
                        return
                      }
                      setTimeStart(v)
                    }}
                    className="block w-full rounded-lg border border-line px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-ink-3">结束时间</span>
                  <input
                    type="datetime-local"
                    min={timeStart || nowLocal()}
                    value={timeEnd}
                    onChange={(e) => {
                      const v = e.target.value
                      if (timeStart && v && v <= timeStart) {
                        showToast('结束时间必须晚于开始时间')
                        return
                      }
                      setTimeEnd(v)
                    }}
                    className="block w-full rounded-lg border border-line px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary"
                  />
                </label>
              </div>
            )}
          </section>
        </div>

        <div className="flex items-center justify-between border-t border-line px-6 py-4">
          <span className="text-sm text-ink-3">
            共 {totalCount} 题 · 总分 {totalScore} 分
          </span>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-line px-5 py-2 text-sm text-ink-2 transition-colors hover:border-ink-3 hover:text-ink"
            >
              取消
            </button>
            <button
              type="button"
              onClick={saveDraft}
              className="rounded-lg border border-primary/40 bg-primary-light/60 px-5 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary-light"
            >
              暂不发布
            </button>
            <button
              type="button"
              onClick={() => void publish()}
              className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-white shadow-[0_4px_12px_rgba(30,111,255,0.30)] transition-all hover:bg-[#1a5fe6] active:scale-[0.97]"
            >
              发布
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
