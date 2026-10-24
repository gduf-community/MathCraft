import { ChevronDown, ChevronRight } from 'lucide-react'
import type { Question } from '../../../types'
import { Latex } from '../../../lib/latex'

interface Props {
  q: Question
  editing: boolean
  expanded: boolean
  onToggle: () => void
  onChange?: (patch: Partial<Question>) => void
}

/** 答案与解析：默认折叠；编辑模式下自动展开并支持修改（LaTeX 以源码形式编辑） */
export default function AnswerPanel({ q, editing, expanded, onToggle, onChange }: Props) {
  const objective = q.options.length > 0
  return (
    <div className="rounded-lg bg-[#fafbfd]">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-1 px-3 py-2 text-[14px] font-medium text-ink-2 transition-colors hover:text-primary"
      >
        {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        答案与解析
      </button>
      {expanded && (
        <div className="space-y-2.5 px-3 pb-3 text-sm leading-6">
          {editing && onChange ? (
            <>
              {objective ? (
                <div className="text-ink-2">
                  <span className="text-ink-3">答案：</span>
                  <span className="font-medium text-primary">{q.answer || '未设置'}</span>
                  <span className="ml-2 text-xs text-ink-3">（在选项右侧勾选正确答案）</span>
                </div>
              ) : (
                <div>
                  <div className="mb-1 text-xs text-ink-3">参考答案（支持 LaTeX 源码）</div>
                  <textarea
                    rows={2}
                    value={q.answer}
                    onChange={(e) => onChange({ answer: e.target.value })}
                    className="block w-full rounded-md border border-primary/40 bg-white p-2 text-sm text-ink outline-none focus:border-primary"
                  />
                </div>
              )}
              <div>
                <div className="mb-1 text-xs text-ink-3">解析（支持 LaTeX 源码）</div>
                <textarea
                  rows={3}
                  value={q.analysis}
                  onChange={(e) => onChange({ analysis: e.target.value })}
                  className="block w-full rounded-md border border-primary/40 bg-white p-2 text-sm leading-6 text-ink outline-none focus:border-primary"
                />
              </div>
            </>
          ) : (
            <>
              <div className="text-ink-2">
                <span className="text-ink-3">答案：</span>
                <Latex text={q.answer} className="font-medium text-ink" />
              </div>
              <div className="text-ink-2">
                <span className="text-ink-3">解析：</span>
                <Latex text={q.analysis} className="text-ink" />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
