/** 文档预览：把简化版 Markdown 渲染成带目录层级的阅读视图，公式交给 KaTeX。 */
import { useEffect, useMemo, useState } from 'react'
import { FileText, Loader2, X } from 'lucide-react'
import { fetchDocumentText } from '../../../api/backend'
import { Latex } from '../../../lib/latex'

type Block =
  | { kind: 'h'; level: number; text: string }
  | { kind: 'p'; text: string }
  | { kind: 'quote'; text: string }
  | { kind: 'li'; text: string; depth: number }
  | { kind: 'math'; text: string }
  | { kind: 'hr' }

/** 按行解析本平台生成的 Markdown：标题、引用、列表、公式块、分隔线。 */
function parseMarkdown(md: string): Block[] {
  const blocks: Block[] = []
  let math: string[] | null = null
  let para: string[] = []
  const flush = () => {
    if (para.length > 0) {
      blocks.push({ kind: 'p', text: para.join(' ') })
      para = []
    }
  }
  for (const raw of md.split(/\r?\n/)) {
    const line = raw.replace(/\s+$/, '')
    if (math !== null) {
      if (line.trim() === '$$') {
        blocks.push({ kind: 'math', text: math.join('\n') })
        math = null
      } else {
        math.push(raw)
      }
      continue
    }
    if (line.trim() === '$$') {
      flush()
      math = []
      continue
    }
    if (!line.trim()) {
      flush()
      continue
    }
    if (/^-{3,}$/.test(line.trim())) {
      flush()
      blocks.push({ kind: 'hr' })
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      flush()
      blocks.push({ kind: 'h', level: heading[1].length, text: heading[2].trim() })
      continue
    }
    if (/^>\s?/.test(line)) {
      flush()
      blocks.push({ kind: 'quote', text: line.replace(/^>\s?/, '') })
      continue
    }
    const item = /^(\s*)[-*]\s+(.*)$/.exec(line)
    if (item) {
      flush()
      blocks.push({ kind: 'li', depth: Math.min(3, Math.floor(item[1].length / 2)), text: item[2].trim() })
      continue
    }
    para.push(line.trim())
  }
  flush()
  if (math !== null) blocks.push({ kind: 'math', text: math.join('\n') })
  return blocks
}

/** 行内渲染：先按 **粗体** 切分，再交给 Latex 处理 $...$。 */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g).filter((p) => p !== '')
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('**') && part.endsWith('**') ? (
          <strong key={i} className="font-semibold text-ink">
            <Latex text={part.slice(2, -2)} />
          </strong>
        ) : (
          <Latex key={i} text={part} />
        ),
      )}
    </>
  )
}

export default function DocPreviewModal({
  bankId,
  docId,
  docName,
  onClose,
}: {
  bankId: string
  docId: string
  docName: string
  onClose: () => void
}) {
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    fetchDocumentText(bankId, docId)
      .then((t) => alive && setText(t))
      .catch((err) => alive && setError(err instanceof Error ? err.message : '打开失败'))
    return () => {
      alive = false
    }
  }, [bankId, docId])
  const blocks = useMemo(() => parseMarkdown(text), [text])

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-[#0f1b33]/50 p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[86vh] w-[900px] max-w-full flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <div className="flex min-w-0 items-center gap-2">
            <FileText size={18} className="shrink-0 text-primary" />
            <h3 className="truncate text-base font-bold text-ink">{docName}</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
          {!text && !error && (
            <div className="flex items-center justify-center gap-2 py-20 text-sm text-ink-3">
              <Loader2 size={16} className="animate-spin" />
              正在载入文档…
            </div>
          )}
          {error && <p className="py-20 text-center text-sm text-red-500">{error}</p>}
          {blocks.map((b, i) => {
            if (b.kind === 'h') {
              if (b.level === 1)
                return (
                  <h1 key={i} className="mb-6 text-center text-2xl font-bold text-ink">
                    <Inline text={b.text} />
                  </h1>
                )
              if (b.level === 2)
                return (
                  <h2 key={i} className="mb-4 mt-8 border-l-4 border-primary pl-3 text-xl font-bold text-ink">
                    <Inline text={b.text} />
                  </h2>
                )
              if (b.level === 3)
                return (
                  <h3 key={i} className="mb-2 mt-6 text-[17px] font-semibold text-ink">
                    <Inline text={b.text} />
                  </h3>
                )
              return (
                <h4 key={i} className="mb-1.5 mt-4 text-[15px] font-semibold text-ink-2">
                  <Inline text={b.text} />
                </h4>
              )
            }
            if (b.kind === 'quote')
              return (
                <p key={i} className="mb-4 rounded-lg bg-page px-4 py-2 text-[13px] leading-6 text-ink-3">
                  <Inline text={b.text} />
                </p>
              )
            if (b.kind === 'li')
              return (
                <p key={i} className="text-sm leading-7 text-ink-2" style={{ paddingLeft: 16 + b.depth * 18 }}>
                  <span className="mr-1.5 text-ink-3">·</span>
                  <Inline text={b.text} />
                </p>
              )
            if (b.kind === 'hr') return <hr key={i} className="my-8 border-line" />
            if (b.kind === 'math')
              return (
                <div key={i} className="my-3 overflow-x-auto py-1 text-center">
                  <Latex text={`$$${b.text}$$`} />
                </div>
              )
            return (
              <p key={i} className="mb-3 text-[15px] leading-7 text-ink">
                <Inline text={b.text} />
              </p>
            )
          })}
        </div>
      </div>
    </div>
  )
}
