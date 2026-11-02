/**
 * 学生作答视图：左侧整卷作答 + 顶部交卷。
 * - 单选/判断：点击选项选中，再次点击取消，选其他项自动切换
 * - 多选：逐项点选/取消
 * - 填空/简答/计算：题干下方长输入框
 * - 交卷 → AI 批卷弹窗（进度条）→ 分数/总分 + OK / 重新作答
 *   OK 进入复盘：锁定作答、展示答案与解析；重新作答清空答案回到作答态（须重新交卷）
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, Loader2 } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { TYPE_LABELS } from '../../../constants'
import type { AssembleRecord, Question } from '../../../types'
import { orderQuestionsByModules } from '../../../lib/order'
import { Latex } from '../../../lib/latex'

interface Props {
  record: AssembleRecord
}

/** 单题作答值：选择题存选中的选项 label，主观题存文本 */
interface AnswerValue {
  choices: string[]
  text: string
}

type Phase = 'answering' | 'review'

const CHOICE_TYPES = new Set(['single', 'multiple', 'judge'])

/** 文本归一化：去空白、统一小写、去全角空格与常见标点差异 */
function normText(s: string) {
  return s
    .replace(/[\s\u3000]+/g, '')
    .replace(/[，,。;；:：'’‘"“”!！?？、（）()]/g, '')
    .toLowerCase()
}

/** 单题判分：返回该题得分 */
function gradeOne(q: Question, value: AnswerValue | undefined): number {
  if (!value) return 0
  if (CHOICE_TYPES.has(q.type)) {
    if (!value.choices.length) return 0
    const correct = (q.answer.match(/[A-Z]/g) ?? []).sort()
    const picked = [...value.choices].sort()
    if (q.type === 'multiple') {
      // 多选：完全一致得满分，否则不得分
      return correct.length && correct.length === picked.length && correct.every((c, i) => c === picked[i]) ? q.score : 0
    }
    return correct.length === 1 && picked.length === 1 && picked[0] === correct[0] ? q.score : 0
  }
  // 主观题：AI 演示批卷 —— 与参考答案一致得满分，作答非空按 60% 给分，空白不得分
  const text = value.text.trim()
  if (!text) return 0
  if (normText(q.answer) && normText(text).includes(normText(q.answer))) return q.score
  return Math.round(q.score * 0.6)
}

export default function AnswerView({ record }: Props) {
  const { markRecordAnswered, showToast } = useApp()
  const questions = useMemo(
    () => orderQuestionsByModules(record.questions, record.modulesOrder),
    [record.questions, record.modulesOrder],
  )
  const totalScore = useMemo(() => questions.reduce((s, q) => s + q.score, 0) || record.totalScore, [questions, record.totalScore])

  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({})
  // 已交卷的记录重开时直接进入复盘态（可查看答案解析，可重新作答）
  const [phase, setPhase] = useState<Phase>(record.answered ? 'review' : 'answering')
  // 批卷弹窗：grading 进度动画 → result 出分
  const [modal, setModal] = useState<null | 'grading' | 'result'>(null)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<{ score: number; total: number } | null>(null)
  const perQuestionScore = useRef<Record<string, number>>({})

  // AI 批卷进度动画： grading 阶段推进到 100 后出结果
  useEffect(() => {
    if (modal !== 'grading') return
    setProgress(0)
    const timer = window.setInterval(() => {
      setProgress((prev) => {
        const next = Math.min(100, prev + 4 + Math.random() * 8)
        if (next >= 100) {
          window.clearInterval(timer)
          window.setTimeout(() => setModal('result'), 260)
        }
        return next
      })
    }, 90)
    return () => window.clearInterval(timer)
  }, [modal])

  const toggleChoice = (q: Question, label: string) => {
    if (phase !== 'answering') return
    setAnswers((prev) => {
      const cur = prev[q.id] ?? { choices: [], text: '' }
      let choices: string[]
      if (q.type === 'multiple') {
        choices = cur.choices.includes(label) ? cur.choices.filter((v) => v !== label) : [...cur.choices, label]
      } else {
        // 单选/判断：再次点击取消，点其他项切换
        choices = cur.choices[0] === label ? [] : [label]
      }
      return { ...prev, [q.id]: { ...cur, choices } }
    })
  }

  const setText = (q: Question, text: string) => {
    if (phase !== 'answering') return
    setAnswers((prev) => ({ ...prev, [q.id]: { choices: [], text } }))
  }

  const submit = () => {
    const answeredCount = Object.values(answers).filter((v) => v.choices.length || v.text.trim()).length
    if (!answeredCount) {
      showToast('请先作答至少一道题再交卷')
      return
    }
    let score = 0
    perQuestionScore.current = {}
    for (const q of questions) {
      const got = gradeOne(q, answers[q.id])
      perQuestionScore.current[q.id] = got
      score += got
    }
    setResult({ score, total: totalScore })
    setModal('grading')
  }

  const confirmOk = () => {
    setModal(null)
    setPhase('review')
    markRecordAnswered(record.id, true)
    showToast('已交卷，可查看答案与解析')
  }

  const restart = () => {
    setModal(null)
    setAnswers({})
    setResult(null)
    setPhase('answering')
    markRecordAnswered(record.id, false)
    showToast('已清空作答，请重新作答并交卷')
  }

  const answeredCount = Object.values(answers).filter((v) => v.choices.length || v.text.trim()).length

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 顶栏：试卷名 + 作答进度 + 交卷 */}
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-6 pb-3 pt-4">
        <span className="text-sm font-bold text-ink">{record.name}</span>
        <span className="rounded-full bg-primary-light px-2.5 py-0.5 text-xs text-primary">作答模式</span>
        <span className="text-xs text-ink-3">
          已答 {answeredCount} / {questions.length} 题 · 满分 {totalScore} 分
        </span>
        <div className="flex-1" />
        {phase === 'review' ? (
          <>
            {result && (
              <span className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3.5 py-1.5 text-sm font-bold text-emerald-600">
                <CheckCircle2 size={15} />
                得分 {result.score} / {result.total}
              </span>
            )}
            {!result && (
              <span className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3.5 py-1.5 text-sm font-bold text-emerald-600">
                <CheckCircle2 size={15} />
                已交卷
              </span>
            )}
            <button
              type="button"
              onClick={restart}
              className="rounded-lg border border-line px-4 py-1.5 text-sm text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
            >
              重新作答
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={submit}
            className="rounded-full bg-primary px-5 py-1.5 text-sm font-medium text-white shadow-[0_2px_8px_rgba(30,111,255,0.30)] transition-all hover:bg-[#1a5fe6] active:scale-[0.97]"
          >
            交卷
          </button>
        )}
      </div>

      {/* 题目列表 */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-8 pt-4">
        {questions.map((q, i) => {
          const value = answers[q.id]
          const locked = phase === 'review'
          return (
            <article key={q.id} className="rounded-xl border border-line bg-white p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-sm font-semibold text-white">
                  {i + 1}
                </span>
                <span className="rounded bg-primary-light px-2 py-0.5 text-xs font-medium text-primary">
                  {TYPE_LABELS[q.type]}
                </span>
                <span className="text-xs text-ink-3">难度：{q.difficulty}</span>
                <span className="ml-auto text-xs text-ink-3">分值 {q.score}</span>
                {phase === 'review' && (
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      (perQuestionScore.current[q.id] ?? 0) >= q.score
                        ? 'bg-emerald-50 text-emerald-600'
                        : (perQuestionScore.current[q.id] ?? 0) > 0
                          ? 'bg-amber-50 text-amber-600'
                          : 'bg-red-50 text-red-500'
                    }`}
                  >
                    得分 {perQuestionScore.current[q.id] ?? 0} / {q.score}
                  </span>
                )}
              </div>
              <p className="mt-2 text-[16px] font-medium leading-7 text-ink">
                <Latex text={q.stem} />
              </p>

              {/* 选择题：可点选的选项 */}
              {q.options.length > 0 && (
                <div className="mt-2.5 space-y-1.5">
                  {q.options.map((o) => {
                    const picked = !!value?.choices.includes(o.label)
                    return (
                      <button
                        key={o.label}
                        type="button"
                        disabled={locked}
                        onClick={() => toggleChoice(q, o.label)}
                        className={`flex w-full items-start gap-2.5 rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                          picked
                            ? 'border-primary bg-primary-light/60 font-medium text-ink'
                            : 'border-line bg-white text-ink-2 hover:border-primary/40'
                        } ${locked ? 'cursor-default' : ''}`}
                      >
                        <span
                          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${
                            picked ? 'border-primary bg-primary text-white' : 'border-ink-3/50 text-ink-3'
                          }`}
                        >
                          {o.label}
                        </span>
                        <span className="flex-1 leading-6">
                          <Latex text={o.text} />
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}

              {/* 主观题：题干下长输入框 */}
              {q.options.length === 0 && (
                <textarea
                  value={value?.text ?? ''}
                  readOnly={locked}
                  onChange={(e) => setText(q, e.target.value)}
                  rows={2}
                  placeholder="在此输入你的答案"
                  className={`mt-2.5 block w-full rounded-lg border px-3 py-2.5 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary ${
                    locked ? 'cursor-default border-line bg-page' : 'border-line bg-white'
                  }`}
                />
              )}

              {/* 复盘：答案与解析 */}
              {phase === 'review' && (
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
              )}
            </article>
          )
        })}
        {!questions.length && <div className="py-16 text-center text-sm text-ink-3">该试卷没有题目快照</div>}
      </div>

      {/* AI 批卷弹窗 */}
      {modal && (
        <div className="fixed inset-0 z-50 flex animate-fade-in items-center justify-center bg-[#0f1b33]/45 p-6">
          <div className="w-[380px] animate-pop rounded-2xl bg-white p-6 shadow-2xl">
            {modal === 'grading' ? (
              <div className="flex flex-col items-center py-2">
                <Loader2 size={34} className="animate-spin text-primary" />
                <h3 className="mt-3.5 text-base font-bold text-ink">AI 正在批卷…</h3>
                <p className="mt-1 text-xs text-ink-3">正在逐题比对答案与评分，请稍候</p>
                <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-primary-light">
                  <div
                    className="h-full rounded-full bg-primary transition-[width] duration-150 ease-out"
                    style={{ width: `${Math.floor(progress)}%` }}
                  />
                </div>
                <p className="mt-1.5 text-xs font-medium text-primary">{Math.floor(progress)}%</p>
              </div>
            ) : (
              result && (
                <div className="flex flex-col items-center py-2">
                  <CheckCircle2 size={38} className="text-emerald-500" />
                  <h3 className="mt-3 text-base font-bold text-ink">批卷完成</h3>
                  <p className="mt-2 flex items-baseline gap-1.5">
                    <span className="text-4xl font-bold leading-none text-primary">{result.score}</span>
                    <span className="text-lg text-ink-3">/ {result.total} 分</span>
                  </p>
                  <div className="mt-5 flex w-full items-center justify-center gap-3">
                    <button
                      type="button"
                      onClick={restart}
                      className="flex-1 rounded-lg border border-line px-4 py-2.5 text-sm text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
                    >
                      重新作答
                    </button>
                    <button
                      type="button"
                      onClick={confirmOk}
                      className="flex-1 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-white shadow-[0_4px_12px_rgba(30,111,255,0.30)] transition-all hover:bg-[#1a5fe6] active:scale-[0.97]"
                    >
                      OK
                    </button>
                  </div>
                </div>
              )
            )}
          </div>
        </div>
      )}
    </div>
  )
}
