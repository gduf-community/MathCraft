/**
 * 讲解视图（教师）：左侧题目列表（解析默认展开，无编辑/删除），右侧可折叠小侧边栏。
 * 题目按组卷时调整后的模块顺序展示与编号，左侧序号与右侧方框完全一致；
 * 侧边栏上半部按题型分区显示题号方框，点击跳转左侧对应题目；
 * 下半部展示当前题目的作答情况（单选/判断/多选按选项人数与比例进度条；分布为演示数据）。
 */
import { useMemo, useRef, useState } from 'react'
import { ChevronsRight, PanelRightClose } from 'lucide-react'
import { TYPE_LABELS } from '../../../constants'
import type { AssembleRecord, Question, StudySpace } from '../../../types'
import { groupOrderedQuestions, orderQuestionsByModules } from '../../../lib/order'
import { Latex } from '../../../lib/latex'

interface Props {
  record: AssembleRecord
  space: StudySpace
}

/** 稳定伪随机：同一题目每次打开分布一致 */
function seededRandom(seed: number) {
  let h = seed ^ 0x9e3779b9
  h = Math.imul(h, 3432918353)
  h = (h << 13) | (h >>> 19)
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507)
    h = Math.imul(h ^ (h >>> 13), 3266489909)
    h ^= h >>> 16
    return (h >>> 0) / 4294967296
  }
}

function hashText(text: string) {
  let h = 5381
  for (let i = 0; i < text.length; i++) h = (h * 33) ^ text.charCodeAt(i)
  return Math.abs(h)
}

type Distribution = { kind: 'options'; options: { label: string; count: number }[] }

/** 演示作答分布：单选/判断按选项分布，多选各选项独立；填空/计算/简答暂无作答统计 */
function demoDistribution(q: Question, respondents: number): Distribution | null {
  if (respondents <= 0) return null
  const rand = seededRandom(hashText(q.id))
  if (q.type === 'single' || q.type === 'judge') {
    const counts = q.options.map(() => 0)
    let left = respondents
    for (let i = 0; i < counts.length; i++) {
      if (i === counts.length - 1) {
        counts[i] = left
      } else {
        const c = Math.floor(rand() * left)
        counts[i] = c
        left -= c
      }
    }
    return { kind: 'options', options: q.options.map((o, i) => ({ label: o.label, count: counts[i] })) }
  }
  if (q.type === 'multiple') {
    // 多选：每人可能选多个，各选项人数独立生成
    const options = q.options.map((o) => ({ label: o.label, count: Math.floor(rand() * (respondents + 1)) }))
    return { kind: 'options', options }
  }
  return null
}

/** 与选项分布一致的进度条行 */
function DistBar({ label, count, total, tone = 'primary' }: { label: string; count: number; total: number; tone?: 'primary' | 'muted' }) {
  const pct = total ? Math.round((count / total) * 100) : 0
  return (
    <li>
      <div className="flex items-center justify-between text-xs text-ink-2">
        <span className="font-medium">{label}</span>
        <span>
          {count} 人 · {pct}%
        </span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-page">
        <div
          className={`h-full rounded-full transition-[width] duration-300 ${tone === 'primary' ? 'bg-primary' : 'bg-ink-3/50'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </li>
  )
}

export default function ExplainView({ record, space }: Props) {
  const studentCount = Math.max(0, space.memberCount - 1)
  const respondents = Math.min(record.submittedCount ?? 0, studentCount)
  // 题目按组卷调整后的模块顺序展示与编号：左右两侧、讲解与作答视图序号完全一致
  const ordered = useMemo(() => orderQuestionsByModules(record.questions, record.modulesOrder), [record.questions, record.modulesOrder])
  const groups = useMemo(() => groupOrderedQuestions(ordered), [ordered])
  const [collapsed, setCollapsed] = useState(false)
  const [currentNo, setCurrentNo] = useState(1)
  const itemRefs = useRef<(HTMLElement | null)[]>([])

  const current = ordered[currentNo - 1] ?? null
  const currentDist = current ? demoDistribution(current, respondents) : null

  const jumpTo = (no: number) => {
    setCurrentNo(no)
    itemRefs.current[no - 1]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="flex min-h-0 flex-1">
      {/* 左侧：题目列表（滚动） */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-8 pt-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="text-sm font-bold text-ink">{record.name}</span>
          <span className="rounded-full bg-primary-light px-2.5 py-0.5 text-xs text-primary">讲解模式</span>
          <span className="text-xs text-ink-3">
            共 {ordered.length} 题 · 交卷 {record.submittedCount ?? 0} / {studentCount}
          </span>
        </div>
        {ordered.map((q, i) => (
          <article
            key={q.id}
            ref={(el) => {
              itemRefs.current[i] = el
            }}
            className="scroll-mt-4 rounded-xl border border-line bg-white p-4"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-sm font-semibold text-white">
                {i + 1}
              </span>
              <span className="rounded bg-primary-light px-2 py-0.5 text-xs font-medium text-primary">
                {TYPE_LABELS[q.type]}
              </span>
              <span className="text-xs text-ink-3">难度：{q.difficulty}</span>
              <span className="ml-auto text-xs text-ink-3">分值 {q.score}</span>
            </div>
            <p className="mt-2 text-[16px] font-medium leading-7 text-ink">
              <Latex text={q.stem} />
            </p>
            {q.options.length > 0 && (
              <div className="mt-2.5 space-y-1.5">
                {q.options.map((o) => (
                  <div key={o.label} className="flex items-start gap-1.5 text-sm text-ink-2">
                    <span className="font-medium">{o.label}.</span>
                    <span>
                      <Latex text={o.text} />
                    </span>
                  </div>
                ))}
              </div>
            )}
            {/* 解析默认展开 */}
            <div className="mt-3 rounded-lg bg-[#fafbfd] px-3 py-2.5 text-sm leading-6">
              <div className="text-ink-2">
                <span className="text-ink-3">答案：</span>
                <Latex text={q.answer} className="font-medium text-ink" />
              </div>
              <div className="mt-1.5 text-ink-2">
                <span className="text-ink-3">解析：</span>
                <Latex text={q.analysis} className="text-ink" />
              </div>
            </div>
          </article>
        ))}
        {!ordered.length && (
          <div className="py-16 text-center text-sm text-ink-3">该试卷没有题目快照，无法讲解</div>
        )}
      </div>

      {/* 右侧：可折叠小侧边栏 */}
      {collapsed ? (
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          title="展开导航"
          className="flex w-9 shrink-0 flex-col items-center gap-2 border-l border-line bg-white py-3 text-ink-3 transition-colors hover:text-primary"
        >
          <ChevronsRight size={16} className="rotate-180" />
          <span className="text-xs [writing-mode:vertical-rl]">题目导航</span>
        </button>
      ) : (
        <aside className="flex w-60 shrink-0 flex-col border-l border-line bg-white">
          <div className="flex items-center justify-between border-b border-line px-3 py-2.5">
            <span className="text-sm font-bold text-ink">题目导航</span>
            <button
              type="button"
              onClick={() => setCollapsed(true)}
              title="向右折叠"
              className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-primary"
            >
              <PanelRightClose size={15} />
            </button>
          </div>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3">
            {groups.map((g) => (
              <div key={g.type}>
                <p className="mb-1.5 text-xs font-medium text-ink-2">{TYPE_LABELS[g.type]}</p>
                <div className="grid grid-cols-4 gap-1.5">
                  {g.items.map(({ q, no }) => (
                    <button
                      key={q.id}
                      type="button"
                      onClick={() => jumpTo(no)}
                      title={`跳转到第 ${no} 题`}
                      className={`rounded-md border py-1.5 text-center text-xs font-medium transition-colors ${
                        currentNo === no
                          ? 'border-primary bg-primary text-white'
                          : 'border-line bg-page text-ink-2 hover:border-primary/50 hover:text-primary'
                      }`}
                    >
                      {no}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {!groups.length && <p className="py-6 text-center text-xs text-ink-3">暂无题目</p>}
          </div>

          {/* 当前题目的作答情况（进度条样式：选项分布 / 填空答对答错） */}
          {current && currentDist && (
            <div className="border-t border-line px-3 py-3">
              <p className="mb-2 text-xs font-bold text-ink">
                作答情况 · 第 {currentNo} 题
                <span className="ml-1.5 font-normal text-ink-3">{TYPE_LABELS[current.type]}</span>
              </p>
              {currentDist.kind === 'options' && currentDist.options && (
                <ul className="space-y-2">
                  {currentDist.options.map((o) => (
                    <DistBar key={o.label} label={`选项 ${o.label}`} count={o.count} total={respondents} />
                  ))}
                </ul>
              )}
              <p className="mt-2 text-[11px] text-ink-3">作答统计为演示数据</p>
            </div>
          )}
          {current && !currentDist && (
            <div className="border-t border-line px-3 py-3">
              <p className="mb-2 text-xs font-bold text-ink">作答情况 · 第 {currentNo} 题</p>
              <p className="text-xs text-ink-3">该题型暂无作答统计</p>
            </div>
          )}
        </aside>
      )}
    </div>
  )
}
