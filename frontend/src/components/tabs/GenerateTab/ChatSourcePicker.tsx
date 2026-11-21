import { BookOpen, Check, ChevronUp, FileText, Search } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { useApp } from '../../../store/AppContext'

const DOC_STATUS_LABELS: Record<string, string> = {
  uploaded: '排队等待解析',
  parsing: '正在解析',
  ocr: 'OCR 识别中',
  chunking: '正在切片',
  embedding: '正在向量化',
}

export function ChatSourcePicker({ disabled }: { disabled: boolean }) {
  const { kbs, docs, selectedKbId, selectedDocId, selectKb, selectDoc,
    sourceDocumentsStatus, retrySourceDocuments } = useApp()
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const pickerRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelId = useId()

  const expanded = open && !disabled
  const selectedBank = kbs.find((bank) => bank.id === selectedKbId)
  const selectedDoc = docs.find((doc) => doc.id === selectedDocId)
  const selection = [selectedBank?.name, selectedDoc?.name].filter(Boolean).join(' / ')
  const filteredBanks = kbs.filter((bank) => bank.name.includes(keyword.trim()))

  function close() {
    setOpen(false)
    setKeyword('')
  }

  useEffect(() => {
    if (!expanded) return
    function handleOutsidePointer(event: PointerEvent) {
      if (event.target instanceof Node && !pickerRef.current?.contains(event.target)) close()
    }
    document.addEventListener('pointerdown', handleOutsidePointer)
    return () => document.removeEventListener('pointerdown', handleOutsidePointer)
  }, [expanded])

  return (
    <div
      ref={pickerRef}
      className="flex min-w-0 flex-[1_1_9rem] items-center gap-2"
      onBlur={(event) => {
        if (expanded && event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) close()
      }}
      onKeyDown={(event) => {
        if (!expanded || event.key !== 'Escape' || event.nativeEvent.isComposing) return
        event.stopPropagation()
        event.preventDefault()
        close()
        triggerRef.current?.focus()
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => (expanded ? close() : setOpen(true))}
        className="flex shrink-0 items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 transition-colors hover:border-primary/60 hover:text-primary focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-45"
      >
        <BookOpen size={14} aria-hidden="true" />
        题库选择
        <ChevronUp size={13} aria-hidden="true" />
      </button>
      {selection && <span className="truncate text-xs text-ink-2" title={selection}>{selection}</span>}
      <div
        id={panelId}
        hidden={!expanded}
        role="region"
        aria-label="选择题库文档"
        className="absolute bottom-full left-0 z-20 mb-2 max-h-[min(22rem,45dvh)] w-80 max-w-full overflow-y-auto overscroll-contain rounded-xl border border-line bg-white p-2.5 shadow-lg"
      >
        {expanded && (
          <>
            <label className="relative block">
              <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
              <input
                autoFocus
                type="search"
                aria-label="搜索题库"
                placeholder="搜索题库"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                className="w-full rounded-md border border-line bg-page py-1.5 pl-8 pr-2 text-sm text-ink outline-none focus:border-primary"
              />
            </label>
            <ul aria-label="题库" className="mt-1 max-h-28 space-y-0.5 overflow-y-auto">
              {filteredBanks.map((bank) => (
                <li key={bank.id}>
                  <button
                    type="button"
                    aria-pressed={bank.id === selectedKbId}
                    onClick={() => { if (bank.id !== selectedKbId) selectKb(bank.id) }}
                    className="flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-ink-2 hover:bg-primary-weak focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary aria-pressed:bg-primary-weak aria-pressed:text-primary"
                  >
                    <span className="truncate">{bank.name}</span>
                    {bank.id === selectedKbId && <Check size={14} aria-hidden="true" className="shrink-0" />}
                  </button>
                </li>
              ))}
              {filteredBanks.length === 0 && <li className="py-2 text-center text-xs text-ink-3">没有匹配的题库</li>}
            </ul>
            <ul aria-label="文档" className="mt-2 space-y-1 border-t border-line pt-2">
              {docs.map((doc) => {
                const selected = doc.id === selectedDocId
                const status = doc.status ?? 'ready'
                const ready = status === 'ready'
                const failed = status === 'failed'
                return (
                  <li key={doc.id}>
                    <button
                      type="button"
                      disabled={!ready}
                      aria-pressed={selected}
                      onClick={() => {
                        selectDoc(doc.id)
                        close()
                        triggerRef.current?.focus()
                      }}
                      className="flex w-full items-center gap-2 rounded-lg border border-line px-2.5 py-2 text-left text-[13px] text-ink-2 hover:border-primary/60 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:bg-page/70 aria-pressed:border-primary/50 aria-pressed:bg-primary-weak"
                    >
                      <FileText size={14} aria-hidden="true" className="shrink-0 text-ink-3" />
                      <span className="min-w-0 flex-1 truncate" title={doc.name}>{doc.name}</span>
                      {selected && <Check size={14} aria-hidden="true" className="shrink-0 text-primary" />}
                      {!ready && (
                        <span className={`shrink-0 text-xs ${failed ? 'text-red-600' : 'text-ink-2'}`}>
                          {failed ? '入库失败' : `${DOC_STATUS_LABELS[status] ?? '处理中'} ${doc.progress ?? 0}%`}
                        </span>
                      )}
                    </button>
                  </li>
                )
              })}
              {sourceDocumentsStatus === 'loading' && (
                <li role="status" className="py-2 text-center text-xs text-ink-3">正在加载文档…</li>
              )}
              {sourceDocumentsStatus === 'error' && (
                <li className="flex items-center justify-center gap-2 py-2 text-xs">
                  <span role="status" className="text-ink-2">加载文档失败</span>
                  <button
                    type="button"
                    onClick={retrySourceDocuments}
                    className="rounded text-primary underline focus-visible:outline-2 focus-visible:outline-primary"
                  >
                    重试加载
                  </button>
                </li>
              )}
              {docs.length === 0 && sourceDocumentsStatus === null && (
                <li className="py-2 text-center text-xs text-ink-3">
                  {selectedKbId ? '该题库暂无文档，可在题库管理中上传' : '请先选择题库'}
                </li>
              )}
            </ul>
          </>
        )}
      </div>
    </div>
  )
}
