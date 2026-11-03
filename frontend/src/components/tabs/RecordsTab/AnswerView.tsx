/**
 * 学生作答视图：真实后端 attempt 流程。
 * 打开时读取已有作答；交卷调后端批卷；复盘读取答案与解析。
 */
import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Loader2 } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { TYPE_LABELS } from '../../../constants'
import type { AssembleRecord, Question } from '../../../types'
import { Latex } from '../../../lib/latex'
import * as api from '../../../api/backend'

interface Props {
  record: AssembleRecord
}

interface AnswerValue {
  choices: string[]
  text: string
}

type Phase = 'answering' | 'review'

export default function AnswerView({ record }: Props) {
  const { spaces, markRecordAnswered, showToast } = useApp()
  const spaceId = useMemo(() => {
    for (const name of record.spaces) {
      const found = spaces.find((s) => s.name === name)
      if (found) return found.id
    }
    return undefined
  }, [record.spaces, spaces])

  const [questions, setQuestions] = useState<Question[]>(record.questions ?? [])
  const [attemptId, setAttemptId] = useState<string | null>(null)
  const [phase, setPhase] = useState<Phase>('answering')
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({})
  const [modal, setModal] = useState<null | 'grading' | 'result'>(null)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<{ score: number; total: number } | null>(null)
  const [perQuestionScore, setPerQuestionScore] = useState<Record<string, number>>({})
  const [totalScore, setTotalScore] = useState(record.totalScore)
  // 交卷后的操作选项（组卷时教师勾选）
  const [allowReview, setAllowReview] = useState(record.allowReview ?? true)
  const [allowRetake, setAllowRetake] = useState(record.allowRetake ?? false)
  const [loading, setLoading] = useState(true)

  const applyPayload = (data: api.ApiAttemptPayload, submitted: boolean) => {
    setQuestions(data.questions.map(api.mapQuestion))
    setAttemptId(data.attempt?.id ?? null)
    setTotalScore(data.paper.total_score)
    setAllowReview(data.paper.allow_review)
    setAllowRetake(data.paper.allow_retake)
    const next: Record<string, AnswerValue> = {}
    for (const a of data.answers) {
      next[a.paper_question_id] = { choices: a.choices, text: a.text }
    }
    setAnswers(next)
    if (submitted) {
      setPhase('review')
      setResult({ score: data.attempt?.score ?? 0, total: data.paper.total_score })
      setPerQuestionScore(Object.fromEntries(data.answers.map((a) => [a.paper_question_id, a.score])))
    } else {
      setPhase('answering')
    }
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void api
      .getAttempt(record.id, spaceId)
      .then((data) => {
        if (cancelled) return
        applyPayload(data, data.attempt?.status === 'submitted')
      })
      .catch((err) => {
        if (cancelled) return
        showToast(err instanceof Error ? err.message : '打开作答页失败')
        setQuestions(record.questions ?? [])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [record.id, spaceId])

  useEffect(() => {
    if (modal !== 'grading') return
    setProgress(5)
    const timer = window.setInterval(() => {
      setProgress((prev) => Math.min(90, prev + 4))
    }, 160)
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
        choices = cur.choices[0] === label ? [] : [label]
      }
      return { ...prev, [q.id]: { ...cur, choices } }
    })
  }

  const setText = (q: Question, text: string) => {
    if (phase !== 'answering') return
    setAnswers((prev) => ({ ...prev, [q.id]: { choices: [], text } }))
  }

  const submit = async () => {
    const answeredCount = Object.values(answers).filter((v) => v.choices.length || v.text.trim()).length
    if (!answeredCount) {
      showToast('请先作答至少一道题再交卷')
      return
    }
    setModal('grading')
    try {
      let id = attemptId
      if (!id) {
        const created = await api.createAttempt(record.id, spaceId)
        id = created.attempt?.id ?? null
        setAttemptId(id)
        setQuestions(created.questions.map(api.mapQuestion))
      }
      if (!id) throw new Error('创建作答记录失败')
      const payload = questions.map((q) => ({
        paper_question_id: q.id,
        choices: answers[q.id]?.choices ?? [],
        text: answers[q.id]?.text ?? '',
      }))
      const res = await api.submitAttempt(id, payload)
      setProgress(100)
      setResult({ score: res.score, total: res.total_score })
      setPerQuestionScore(Object.fromEntries(res.detail.map((d) => [d.paper_question_id, d.score])))
      window.setTimeout(() => setModal('result'), 200)
    } catch (err) {
      setModal(null)
      showToast(err instanceof Error ? err.message : '交卷失败')
    }
  }

  const confirmOk = async () => {
    // 查看答案与解析：读取带答案的复盘数据
    setModal(null)
    setPhase('review')
    markRecordAnswered(record.id, true)
    if (!attemptId) return
    try {
      const review = await api.reviewAttempt(attemptId)
      applyPayload(review, true)
      showToast('已交卷，可查看答案与解析')
    } catch {
      showToast('已交卷，可重新打开查看解析')
    }
  }

  /** 修改答案：基于上一次提交的答案重新进入作答，可修改后再次交卷 */
  const modifyAnswer = async () => {
    setModal(null)
    try {
      const created = await api.createAttempt(record.id, spaceId)
      applyPayload(created, false)
      setResult(null)
      setPerQuestionScore({})
      markRecordAnswered(record.id, false)
      showToast('已回到作答，可修改答案后重新交卷')
    } catch (err) {
      showToast(err instanceof Error ? err.message : '修改答案失败')
    }
  }

  const answeredCount = Object.values(answers).filter((v) => v.choices.length || v.text.trim()).length

  if (loading) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center gap-2 text-sm text-ink-3">
        <Loader2 size={18} className="animate-spin text-primary" />
        正在加载作答…
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
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
            {allowRetake && (
              <button
                type="button"
                onClick={() => void modifyAnswer()}
                className="rounded-lg border border-line px-4 py-1.5 text-sm text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
              >
                修改答案
              </button>
            )}
          </>
        ) : (
          <button
            type="button"
            onClick={() => void submit()}
            className="rounded-full bg-primary px-5 py-1.5 text-sm font-medium text-white shadow-[0_2px_8px_rgba(30,111,255,0.30)] transition-all hover:bg-[#1a5fe6] active:scale-[0.97]"
          >
            交卷
          </button>
        )}
      </div>

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
                      (perQuestionScore[q.id] ?? 0) >= q.score
                        ? 'bg-emerald-50 text-emerald-600'
                        : (perQuestionScore[q.id] ?? 0) > 0
                          ? 'bg-amber-50 text-amber-600'
                          : 'bg-red-50 text-red-500'
                    }`}
                  >
                    得分 {perQuestionScore[q.id] ?? 0} / {q.score}
                  </span>
                )}
              </div>
              <p className="mt-2 text-[16px] font-medium leading-7 text-ink">
                <Latex text={q.stem} />
              </p>

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

              {phase === 'review' && !!q.answer && (
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
                  {/* 按组卷时的「交卷后的操作」选项显示对应按钮 */}
                  <div className="mt-5 flex w-full items-center justify-center gap-3">
                    {allowRetake && (
                      <button
                        type="button"
                        onClick={() => void modifyAnswer()}
                        className="flex-1 rounded-lg border border-line px-4 py-2.5 text-sm text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
                      >
                        修改答案
                      </button>
                    )}
                    {allowReview && (
                      <button
                        type="button"
                        onClick={() => void confirmOk()}
                        className="flex-1 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-white shadow-[0_4px_12px_rgba(30,111,255,0.30)] transition-all hover:bg-[#1a5fe6] active:scale-[0.97]"
                      >
                        查看答案与解析
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => {
                        setModal(null)
                        setPhase('review')
                        markRecordAnswered(record.id, true)
                      }}
                      className="flex-1 rounded-lg border border-line px-4 py-2.5 text-sm text-ink-2 transition-colors hover:bg-page"
                    >
                      完成
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
