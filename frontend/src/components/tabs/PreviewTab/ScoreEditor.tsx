import { useEffect, useRef, useState } from 'react'
import { Check, Pencil } from 'lucide-react'

interface Props {
  value: number
  /** 处于整卡编辑态时，修改只写入草稿，由「保存」统一提交 */
  editing: boolean
  onChange: (v: number) => void
}

/** 分值展示与行内编辑，位于题目卡片右侧 */
export default function ScoreEditor({ value, editing, onChange }: Props) {
  const [active, setActive] = useState(false)
  const [draft, setDraft] = useState(String(value))
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!active) setDraft(String(value))
  }, [value, active])

  useEffect(() => {
    if (active) inputRef.current?.select()
  }, [active])

  const commit = () => {
    setActive(false)
    const v = Math.max(1, Math.min(100, Math.round(Number(draft) || value)))
    if (v !== value) onChange(v)
  }

  return (
    <div className="flex items-center gap-1">
      {active ? (
        <>
          <span className="text-xs text-ink-3">(</span>
          <input
            ref={inputRef}
            value={draft}
            autoFocus
            onChange={(e) => setDraft(e.target.value.replace(/[^\d]/g, ''))}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit()
              if (e.key === 'Escape') setActive(false)
            }}
            className="h-6 w-12 rounded border border-primary bg-white text-center text-xs text-ink outline-none"
          />
          <span className="text-xs text-ink-3">分)</span>
          <button
            type="button"
            title="确认"
            onMouseDown={(e) => {
              e.preventDefault()
              commit()
            }}
            className="rounded p-0.5 text-primary hover:bg-primary-light"
          >
            <Check size={13} />
          </button>
        </>
      ) : (
        <>
          <span className={`rounded px-2 py-0.5 text-xs ${editing ? 'bg-primary-light text-primary' : 'bg-page text-ink-2'}`}>
            ({value}分)
          </span>
          <button
            type="button"
            title="修改分值"
            onClick={() => setActive(true)}
            className="rounded p-0.5 text-ink-3 transition-colors hover:bg-primary-light hover:text-primary"
          >
            <Pencil size={12} />
          </button>
        </>
      )}
    </div>
  )
}
