import { useState } from 'react'
import { Check, ChevronDown } from 'lucide-react'

interface Option {
  value: string
  label: string
}

interface Props {
  value: string
  options: Option[]
  onChange: (value: string) => void
  placeholder?: string
  className?: string
}

/** 轻量下拉选择组件，知识库选择、难度筛选共用 */
export default function Dropdown({ value, options, onChange, placeholder, className = '' }: Props) {
  const [open, setOpen] = useState(false)
  const current = options.find((o) => o.value === value)
  return (
    <div className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink transition-colors hover:border-primary/60"
      >
        <span className="truncate">{current?.label ?? placeholder ?? '请选择'}</span>
        <ChevronDown size={15} className={`shrink-0 text-ink-3 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute left-0 right-0 top-full z-30 mt-1 max-h-60 overflow-y-auto rounded-lg border border-line bg-white py-1 shadow-lg">
            {options.map((o) => (
              <button
                key={o.value}
                type="button"
                onClick={() => {
                  onChange(o.value)
                  setOpen(false)
                }}
                className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-primary-weak ${
                  o.value === value ? 'text-primary' : 'text-ink'
                }`}
              >
                <span className="truncate">{o.label}</span>
                {o.value === value && <Check size={14} />}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
