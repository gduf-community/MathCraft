import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, X } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { TYPE_LABELS, TYPE_ORDER } from '../../../constants'
import type { PaperModule } from '../../../types'

interface Props {
  onClose: () => void
}

/**
 * 组卷弹窗：
 * - 按题型模块（而非单个题目）排序，提供上移/下移
 * - 发布到学习空间（多选）
 * - 顶部「保存到组卷记录」复选框，默认勾选
 * - 底部「发布」「取消」
 */
export default function AssembleModal({ onClose }: Props) {
  const { questions, selectedIds, spaces, publishPaper } = useApp()

  // 已勾选题目参与组卷；未勾选时默认使用当前全部题目
  const pool = useMemo(
    () => (selectedIds.length ? questions.filter((q) => selectedIds.includes(q.id)) : questions),
    [questions, selectedIds],
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
  const [chosenSpaces, setChosenSpaces] = useState<string[]>([])
  const [saveRecord, setSaveRecord] = useState(true)

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

  const publish = async () => {
    const ok = await publishPaper(modules, chosenSpaces, saveRecord)
    if (ok) onClose()
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
          <h3 className="text-base font-bold text-ink">组卷发布 · 演示</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
          <p className="rounded-lg bg-primary-light px-3 py-2 text-sm text-ink-2">当前为组卷演示，所选学习空间不会实际接收题目，学生作答尚未开放。组卷记录仅保留在本次会话中。</p>
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
              onClick={() => void publish()}
              className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-white shadow-[0_4px_12px_rgba(30,111,255,0.30)] transition-all hover:bg-[#1a5fe6] active:scale-[0.97]"
            >
              完成演示
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
