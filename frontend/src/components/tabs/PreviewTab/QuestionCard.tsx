import { useEffect, useState } from 'react'
import { Pencil, Save, Star, Trash2, X } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { useFavorites } from '../../../store/FavoritesContext'
import { TYPE_LABELS } from '../../../constants'
import type { Question } from '../../../types'
import { Latex } from '../../../lib/latex'
import AnswerPanel from './AnswerPanel'
import ScoreEditor from './ScoreEditor'

interface Props {
  q: Question
  index: number
}

/** 题目卡片：题号/收藏、题干选项、答案解析折叠区、右侧分值与操作 */
export default function QuestionCard({ q, index }: Props) {
  const { selectedIds, toggleSelect, updateQuestion, deleteQuestion } = useApp()
  const { isFavorite, toggleFavorite, updateQuestionSnapshot } = useFavorites()
  const [editing, setEditing] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [draft, setDraft] = useState<Question>(q)

  useEffect(() => {
    if (!editing) setDraft(q)
  }, [q, editing])

  const startEdit = () => {
    setDraft({ ...q, options: q.options.map((o) => ({ ...o })) })
    setExpanded(true)
    setEditing(true)
  }

  const cancelEdit = () => {
    setDraft(q)
    setEditing(false)
  }

  const saveEdit = async () => {
    await updateQuestion(draft)
    // 已收藏的题目同步快照，避免收藏页继续显示旧题干
    await updateQuestionSnapshot(draft)
    setEditing(false)
  }

  const selected = selectedIds.includes(q.id)
  const starred = isFavorite(q.id)
  const objective = draft.options.length > 0

  const patchDraft = (patch: Partial<Question>) => setDraft((prev) => ({ ...prev, ...patch }))

  const setOptionText = (label: string, text: string) =>
    patchDraft({ options: draft.options.map((o) => (o.label === label ? { ...o, text } : o)) })

  const toggleCorrect = (label: string) => {
    if (q.type === 'single' || q.type === 'judge') {
      patchDraft({ answer: label })
    } else {
      const set = new Set(draft.answer.split(''))
      if (set.has(label)) set.delete(label)
      else set.add(label)
      patchDraft({ answer: [...set].sort().join('') })
    }
  }

  const changeScore = (v: number) => {
    if (editing) patchDraft({ score: v })
    else void updateQuestion({ ...q, score: v })
  }

  return (
    <article
      className={`rounded-xl border bg-white p-4 transition-shadow hover:shadow-[0_4px_16px_rgba(30,90,180,0.08)] ${
        selected
          ? 'border-primary/60 shadow-[0_0_0_1px_rgba(30,111,255,0.25),0_4px_16px_rgba(30,90,180,0.08)]'
          : 'border-line'
      }`}
    >
      <div className="flex gap-3.5">
        {/* 左侧：选择框、题号、收藏星标 */}
        <div className="flex flex-col items-center gap-1.5 pt-0.5">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => toggleSelect(q.id)}
            className="h-4 w-4 accent-primary"
          />
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-page text-[16px] font-semibold text-ink-2">
            {index}
          </span>
          <button
            type="button"
            title={starred ? '取消收藏' : '收藏本题'}
            aria-pressed={starred}
            onClick={() => void toggleFavorite(q)}
            className={`transition-transform hover:scale-110 ${starred ? 'text-star' : 'text-ink-3/70'}`}
          >
            <Star size={16} fill={starred ? 'currentColor' : 'none'} />
          </button>
        </div>

        {/* 中间：题目主体 */}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-primary-light px-2 py-0.5 text-xs font-medium text-primary">
              {TYPE_LABELS[q.type]}
            </span>
            <span className="text-xs text-ink-3">难度：{q.difficulty}</span>
          </div>

          {editing ? (
            <textarea
              rows={2}
              value={draft.stem}
              onChange={(e) => patchDraft({ stem: e.target.value })}
              className="mt-2.5 block w-full rounded-lg border border-primary/40 bg-primary-weak/40 p-2.5 text-sm leading-6 text-ink outline-none focus:border-primary"
            />
          ) : (
            <p className="mt-2 text-[16px] font-medium leading-7 text-ink">
              <Latex text={q.stem} />
            </p>
          )}

          {/* 选项 */}
          {objective && (
            <div className="mt-2.5 flex flex-wrap gap-x-10 gap-y-2">
              {draft.options.map((o) => (
                <div key={o.label} className="flex items-center gap-1.5 text-sm text-ink-2">
                  <span className="font-medium">{o.label}.</span>
                  {editing ? (
                    <>
                      <input
                        value={o.text}
                        onChange={(e) => setOptionText(o.label, e.target.value)}
                        className="w-44 rounded-md border border-primary/40 bg-primary-weak/40 px-2 py-1 text-sm text-ink outline-none focus:border-primary"
                      />
                      <label className="flex cursor-pointer items-center gap-1 text-xs text-ink-3">
                        <input
                          type="checkbox"
                          checked={draft.answer.includes(o.label)}
                          onChange={() => toggleCorrect(o.label)}
                          className="h-3.5 w-3.5 accent-primary"
                        />
                        答案
                      </label>
                    </>
                  ) : (
                    <span>
                      <Latex text={o.text} />
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* 答案与解析（默认折叠，编辑时自动展开） */}
          <div className="mt-3">
            <AnswerPanel
              q={editing ? draft : q}
              editing={editing}
              expanded={expanded}
              onToggle={() => setExpanded((v) => !v)}
              onChange={patchDraft}
            />
          </div>
        </div>

        {/* 右侧：分值（可编辑）+ 编辑/删除 */}
        <div className="flex shrink-0 flex-col items-end gap-2">
          <ScoreEditor value={editing ? draft.score : q.score} editing={editing} onChange={changeScore} />
          <div className="flex items-center gap-2">
            {editing ? (
              <>
                <button
                  type="button"
                  onClick={() => void saveEdit()}
                  className="flex items-center gap-1 rounded-full border border-primary bg-primary px-3.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-[#1a5fe6]"
                >
                  <Save size={13} /> 保存
                </button>
                <button
                  type="button"
                  onClick={cancelEdit}
                  className="flex items-center gap-1 rounded-full border border-line px-3.5 py-1.5 text-xs text-ink-2 transition-colors hover:border-ink-3 hover:text-ink"
                >
                  <X size={13} /> 取消
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={startEdit}
                  className="flex items-center gap-1 rounded-full border border-primary/40 bg-primary-weak px-3.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary-light"
                >
                  <Pencil size={13} /> 编辑
                </button>
                <button
                  type="button"
                  onClick={() => void deleteQuestion(q.id)}
                  className="flex items-center gap-1 rounded-full border border-danger/40 bg-white px-3.5 py-1.5 text-xs font-medium text-danger transition-colors hover:bg-[#fef2f2]"
                >
                  <Trash2 size={13} /> 删除
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      <p className="mt-2 pl-[54px] text-xs text-ink-3">所属知识点：{q.knowledgePoint}</p>
    </article>
  )
}
