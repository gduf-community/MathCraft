/** 有界 MD/TXT 预览；传输、渲染与交互都绑定当前文档生命周期。 */
import { Download, FileText, Loader2, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { downloadDocument, fetchDocumentText } from '../../../api/backend'
import { isDocumentPreviewCancelled } from '../../../api/documentPreview'
import type { TextDocumentFormat } from '../../../api/documentPreview'
import { onSessionCleared } from '../../../api/session'
import { Latex } from '../../../lib/latex'
import { buildDocumentPreviewPages } from './documentPreviewBlocks'
import type { DocumentPreviewBlock } from './documentPreviewBlocks'

interface DocPreviewProps {
  bankId: string
  docId: string
  docName: string
  docFormat?: string
  onClose: () => void
}

const buttonClass = 'min-h-11 rounded-lg border border-line px-3 text-sm text-ink transition-colors hover:bg-page focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50'

function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g).filter(part => part !== '')
  return <>{parts.map((part, index) => part.startsWith('**') && part.endsWith('**')
    ? <strong key={index} className="font-semibold text-ink"><Latex text={part.slice(2, -2)} /></strong>
    : <Latex key={index} text={part} />)}</>
}

function PreviewBlock({ block }: { block: DocumentPreviewBlock }) {
  if (block.kind === 'plain') return <div className="mb-3">
    <pre className="whitespace-pre-wrap break-words font-sans text-[15px] leading-7 text-ink">{block.text}</pre>
    {block.truncated && <p role="status" className="mt-3 text-sm text-ink-3">本段超过 2 万字符，已按纯文本截断显示；请使用「下载文档」查看完整内容。</p>}
  </div>
  if (block.kind === 'hr') return <hr className="my-8 border-line" />
  if (block.kind === 'h') {
    const content = <Inline text={block.text} />
    if (block.level === 1) return <h1 className="mb-6 text-center text-2xl font-bold text-ink">{content}</h1>
    if (block.level === 2) return <h2 className="mb-4 mt-8 border-l-4 border-primary pl-3 text-xl font-bold text-ink">{content}</h2>
    if (block.level === 3) return <h3 className="mb-2 mt-6 text-[17px] font-semibold text-ink">{content}</h3>
    return <h4 className="mb-1.5 mt-4 text-[15px] font-semibold text-ink-2">{content}</h4>
  }
  if (block.kind === 'quote') return <blockquote className="mb-4 rounded-lg bg-page px-4 py-2 text-sm leading-6 text-ink-3"><Inline text={block.text} /></blockquote>
  if (block.kind === 'li') return <p className="text-sm leading-7 text-ink-2" style={{ paddingLeft: 16 + block.depth * 18 }}>
    <span aria-hidden="true" className="mr-1.5 text-ink-3">·</span><Inline text={block.text} />
  </p>
  if (block.kind === 'math') return <div className="my-3 overflow-x-auto py-1 text-center"><Latex text={`$$${block.text}$$`} /></div>
  return <p className="mb-3 text-[15px] leading-7 text-ink"><Inline text={block.text} /></p>
}

function TextDocumentPreview({ bankId, docId, docName, docFormat = 'MD', onClose }: DocPreviewProps) {
  const textFormat: TextDocumentFormat = docFormat === 'TXT' ? 'TXT' : 'MD'
  const [result, setResult] = useState<{ text: string; error: string } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [pageIndex, setPageIndex] = useState(0)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')
  const request = useRef<AbortController | null>(null)
  const download = useRef<AbortController | null>(null)
  const dialog = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const closeCallback = useRef(onClose)
  useEffect(() => { closeCallback.current = onClose }, [onClose])
  useEffect(() => () => { download.current?.abort() }, [])
  useEffect(() => {
    const previousFocus = document.activeElement
    closeButton.current?.focus()
    return () => { if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus() }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    request.current = controller
    const unsubscribe = onSessionCleared(() => {
      controller.abort()
      download.current?.abort()
      closeCallback.current()
    })
    async function load() {
      try {
        if (docFormat !== 'MD' && docFormat !== 'TXT') {
          setResult({ text: '', error: '该格式不支持文本预览，请下载文档查看' })
          return
        }
        const text = await fetchDocumentText(bankId, docId, controller.signal, docFormat)
        if (!controller.signal.aborted) setResult({ text, error: '' })
      } catch (error: unknown) {
        if (!controller.signal.aborted && !isDocumentPreviewCancelled(error)) {
          setResult({ text: '', error: error instanceof Error ? error.message : '打开失败，请重试或下载文档' })
        }
      }
    }
    void load()
    return () => {
      controller.abort()
      unsubscribe()
    }
  }, [bankId, docId, docFormat, attempt])

  const pages = useMemo(() => buildDocumentPreviewPages(result?.text ?? '', textFormat), [result?.text, textFormat])
  const close = () => {
    request.current?.abort()
    download.current?.abort()
    onClose()
  }
  const retry = () => {
    setResult(null)
    setPageIndex(0)
    setAttempt(value => value + 1)
  }
  const changePage = (index: number) => {
    setPageIndex(index)
    content.current?.scrollTo({ top: 0 })
    content.current?.focus()
  }
  const startDownload = async () => {
    if (download.current && !download.current.signal.aborted) return
    const controller = new AbortController()
    download.current = controller
    setDownloading(true)
    setDownloadError('')
    try {
      await downloadDocument(bankId, docId, docName, controller.signal)
    } catch (error: unknown) {
      if (!controller.signal.aborted && !isDocumentPreviewCancelled(error)) {
        setDownloadError(error instanceof Error ? error.message : '下载失败，请重试')
      }
    } finally {
      if (!controller.signal.aborted) setDownloading(false)
      if (download.current === controller) download.current = null
    }
  }

  return <div
    ref={dialog}
    className="fixed inset-0 z-[60] flex items-center justify-center bg-[#0f1b33]/50 p-4"
    onClick={event => { event.stopPropagation(); close() }}
    onKeyDown={event => {
      event.stopPropagation()
      if (event.key === 'Escape') { event.preventDefault(); close() }
      if (event.key === 'Tab') {
        const controls = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), [tabindex="0"]')
        const first = controls?.[0], last = controls?.[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }}
    role="dialog" aria-modal="true" aria-label={`文档预览：${docName}`}
  >
    <div className="flex h-[86vh] w-[900px] max-w-full flex-col overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={event => event.stopPropagation()}>
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3 sm:px-6">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <FileText size={18} aria-hidden="true" className="shrink-0 text-primary" />
          <h2 className="truncate text-base font-bold text-ink">{docName}</h2>
        </div>
        <button type="button" className={buttonClass} disabled={downloading} onClick={() => { void startDownload() }}>
          <Download size={16} aria-hidden="true" className="mr-1 inline" />{downloading ? '正在下载…' : '下载文档'}
        </button>
        <button ref={closeButton} type="button" onClick={close} aria-label="关闭文档预览" className={`${buttonClass} flex min-w-11 items-center justify-center`}><X size={18} aria-hidden="true" /></button>
      </header>
      {downloadError && <p role="alert" className="px-6 py-2 text-sm text-red-700">{downloadError}</p>}
      <div ref={content} tabIndex={0} aria-label="文档预览内容" aria-busy={!result} className="min-h-0 flex-1 overflow-y-auto break-words px-4 py-6 focus-visible:outline-2 focus-visible:outline-primary sm:px-8">
        {!result && <div role="status" className="flex items-center justify-center gap-2 py-20 text-sm text-ink-3"><Loader2 size={16} aria-hidden="true" className="animate-spin motion-reduce:animate-none" />正在载入文档…</div>}
        {result?.error && <div className="py-12 text-center"><p role="alert" className="mb-4 text-sm text-red-700">{result.error}</p><button type="button" className={buttonClass} onClick={retry}>重试预览</button></div>}
        {result && !result.error && pages.length === 0 && <p role="status" className="py-20 text-center text-sm text-ink-3">文档暂无可预览内容</p>}
        {pages[pageIndex]?.map(block => <PreviewBlock key={block.id} block={block} />)}
      </div>
      {pages.length > 0 && <nav aria-label="文档预览分页" className="flex flex-wrap items-center justify-center gap-3 border-t border-line px-4 py-3">
        <button type="button" className={buttonClass} disabled={pageIndex === 0} onClick={() => changePage(pageIndex - 1)}>上一页</button>
        <span role="status" aria-live="polite" className="text-sm text-ink-3">第 {pageIndex + 1} / {pages.length} 页</span>
        <button type="button" className={buttonClass} disabled={pageIndex + 1 >= pages.length} onClick={() => changePage(pageIndex + 1)}>下一页</button>
      </nav>}
    </div>
  </div>
}

/** 默认 MD 保持旧入口兼容；文档或格式切换时立即卸载并取消旧预览。 */
export default function DocPreviewModal(props: DocPreviewProps) {
  const format = (props.docFormat ?? 'MD').trim().toUpperCase()
  return <TextDocumentPreview key={JSON.stringify([props.bankId, props.docId, format])} {...props} docFormat={format} />
}
