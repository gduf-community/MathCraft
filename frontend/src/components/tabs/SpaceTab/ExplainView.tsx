/**
 * 讲解视图（教师）：左侧题目列表（解析默认展开），右侧题目导航与真实作答统计。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronsRight, PanelRightClose } from 'lucide-react'
import { TYPE_LABELS } from '../../../constants'
import type { AssembleRecord, StudySpace } from '../../../types'
import { groupOrderedQuestions, orderQuestionsByModules } from '../../../lib/order'
import { Latex } from '../../../lib/latex'
import { useApp } from '../../../store/AppContext'
import { getStatistics } from '../../../api/backend'
import type { ApiStatistics } from '../../../api/backend'

interface Props {
  record: AssembleRecord
  space: StudySpace
}

function DistBar({ label, count, total }: { label: string; count: number; total: number }) {
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
        <div className="h-full rounded-full bg-primary transition-[width] duration-300" style={{ width: `${pct}%` }} />
      </div>
    </li>
  )
}

export default function ExplainView({ record, space }: Props) {
  const { showToast } = useApp()
  const [stats, setStats] = useState<ApiStatistics | null>(null)

  useEffect(() => {
    let cancelled = false
    void getStatistics(record.id, space.id)
      .then((data) => {
        if (!cancelled) setStats(data)
      })
      .catch((err) => {
        if (!cancelled) showToast(err instanceof Error ? err.message : '加载统计失败')
      })
    return () => {
      cancelled = true
    }
  }, [record.id, space.id, showToast])

  const studentCount = stats?.student_count ?? Math.max(0, space.memberCount - 1)
  const respondents = stats?.submitted_count ?? record.submittedCount ?? 0
  const ordered = useMemo(
    () => orderQuestionsByModules(record.questions, record.modulesOrder),
    [record.questions, record.modulesOrder],
  )
  const groups = useMemo(() => groupOrderedQuestions(ordered), [ordered])
  const [collapsed, setCollapsed] = useState(false)
  const [currentNo, setCurrentNo] = useState(1)
  const itemRefs = useRef<(HTMLElement | null)[]>([])

  const current = ordered[currentNo - 1] ?? null
  const currentStat = current ? stats?.questions.find((q) => q.paper_question_id === current.id) : undefined
  const currentDist = currentStat?.option_counts ?? null

  const jumpTo = (no: number) => {
    setCurrentNo(no)
    itemRefs.current[no - 1]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="flex min-h-0 flex-1">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-8 pt-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="text-sm font-bold text-ink">{record.name}</span>
          <span className="rounded-full bg-primary-light px-2.5 py-0.5 text-xs text-primary">讲解模式</span>
          <span className="text-xs text-ink-3">
            共 {ordered.length} 题 · 交卷 {respondents} / {studentCount}
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
        {!ordered.length && <div className="py-16 text-center text-sm text-ink-3">该试卷没有题目快照，无法讲解</div>}
      </div>

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

          {current && (
            <div className="border-t border-line px-3 py-3">
              <p className="mb-2 text-xs font-bold text-ink">
                作答情况 · 第 {currentNo} 题
                <span className="ml-1.5 font-normal text-ink-3">{TYPE_LABELS[current.type]}</span>
              </p>
              {currentDist ? (
                <ul className="space-y-2">
                  {currentDist.map((o) => (
                    <DistBar key={o.label} label={`选项 ${o.label}`} count={o.count} total={respondents} />
                  ))}
                </ul>
              ) : currentStat ? (
                <div className="space-y-1 text-xs text-ink-3">
                  <p>平均分：{currentStat.average_score}</p>
                  <p>正确率：{Math.round(currentStat.correct_rate * 100)}%</p>
                </div>
              ) : (
                <p className="text-xs text-ink-3">暂无作答统计</p>
              )}
            </div>
          )}
        </aside>
      )}
    </div>
  )
}
