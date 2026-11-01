import { useState } from 'react'
import { Check, ChevronDown, Search } from 'lucide-react'

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
  /** 展开时显示搜索框，按选项文本过滤 */
  searchable?: boolean
  /** 无匹配选项时的提示文案 */
  emptyText?: string
}

/** 轻量下拉选择组件，知识库选择、难度筛选共用；面板高度受限，超出的选项滚动查看 */
export default function Dropdown({ value, options, onChange, placeholder, className = '', searchable = false, emptyText }: Props) {
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const current = options.find((o) => o.value === value)
  const kw = keyword.trim()
  const filtered = kw ? options.filter((o) => o.label.includes(kw)) : options

  const close = () => {
    setOpen(false)
    setKeyword('')
  }

  return (
    <div className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => (open ? close() : setOpen(true))}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink transition-colors hover:border-primary/60"
      >
        <span className={`truncate ${current ? '' : 'text-ink-3'}`}>{current?.label ?? placeholder ?? '请选择'}</span>
        <ChevronDown size={15} className={`shrink-0 text-ink-3 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={close} />
          <div className="absolute left-0 right-0 top-full z-30 mt-1 flex max-h-60 flex-col overflow-hidden rounded-lg border border-line bg-white py-1 shadow-lg">
            {searchable && (
              <div className="relative shrink-0 px-2 pb-1 pt-0.5">
                <Search size={13} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-3" />
                <input
                  autoFocus
                  type="text"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="搜索"
                  className="block w-full rounded-md border border-line bg-page py-1.5 pl-7 pr-2 text-xs text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
                />
              </div>
            )}
            <div className="min-h-0 flex-1 overflow-y-auto">
              {filtered.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => {
                    onChange(o.value)
                    close()
                  }}
                  className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-primary-weak ${
                    o.value === value ? 'text-primary' : 'text-ink'
                  }`}
                >
                  <span className="truncate">{o.label}</span>
                  {o.value === value && <Check size={14} />}
                </button>
              ))}
              {!filtered.length && (
                <p className="py-4 text-center text-xs text-ink-3">{emptyText ?? '没有匹配的选项'}</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
