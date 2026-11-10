/** 题库管理页共享小组件：头像、格式徽标、权限开关 */
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { useId, useRef, useState } from 'react'
import { FileUp } from 'lucide-react'
import type { BankDoc } from '../../../api/banks'
import { DOCUMENT_ACCEPT } from './uploadFiles'

/** 原生按钮提供键盘选择入口；拖放只由虚线区接收。 */
export function DocumentDropZone({
  onFiles, busy = false,
}: {
  onFiles: (files: File[]) => void
  busy?: boolean
}) {
  const input = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  return (
    <div>
      <button
        type="button"
        aria-label="选择或拖入文档"
        aria-busy={busy}
        onClick={() => input.current?.click()}
        onDragOver={(event) => { event.preventDefault(); setDragOver(true) }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget instanceof Node ? event.relatedTarget : null)) {
            setDragOver(false)
          }
        }}
        onDrop={(event) => {
          event.preventDefault()
          setDragOver(false)
          onFiles(Array.from(event.dataTransfer.files))
        }}
        className={`flex w-full cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed px-4 py-5 text-center transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${dragOver ? 'border-primary bg-primary-light/40' : 'border-line hover:border-primary/50 hover:bg-page'}`}
      >
        <FileUp size={20} className="text-primary" aria-hidden="true" />
        <span className="text-sm text-ink-2">{busy ? '正在批量上传，请等待完成' : '点击选择或拖拽多个文件到此处上传'}</span>
        <span className="text-xs text-ink-3">支持 PDF / DOCX / XLSX / MD / markdown / TXT</span>
        <span className="text-xs text-ink-3">仅此虚线区接受拖放；可按 Enter 或空格选择文件，大小限制以服务端为准</span>
      </button>
      <input
        ref={input}
        type="file"
        multiple
        accept={DOCUMENT_ACCEPT}
        aria-label="上传文档"
        className="hidden"
        onChange={(event) => {
          onFiles(Array.from(event.target.files ?? []))
          event.target.value = ''
        }}
      />
    </div>
  )
}

/** 错误正文可选中复制，按钮暴露展开状态，重试在受理后由父级刷新。 */
export function DocumentFailure({ doc, onRetry }: { doc: BankDoc; onRetry?: () => Promise<void> }) {
  const id = useId()
  const [expanded, setExpanded] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const retryLock = useRef(false)
  if (doc.status !== 'failed') return null
  return (
    <div className="mt-2 space-y-2 text-sm">
      <div className="flex gap-3">
        <button type="button" aria-expanded={expanded} aria-controls={id}
          onClick={() => setExpanded((value) => !value)}
          className="rounded px-2 py-1 text-red-700 underline focus-visible:outline-2 focus-visible:outline-primary">
          {expanded ? '收起失败详情' : '展开失败详情'}
        </button>
        {onRetry && <button type="button" disabled={retrying}
          className="rounded px-2 py-1 text-primary underline focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-50"
          onClick={async () => {
            if (retryLock.current) return
            retryLock.current = true
            setRetrying(true)
            try { await onRetry() } finally { retryLock.current = false; setRetrying(false) }
          }}>
          {retrying ? '重新排队中…' : '重新解析'}
        </button>}
      </div>
      <div id={id} hidden={!expanded}>
        <p className="mb-1 text-xs text-ink-3">可选择下方文本复制错误详情</p>
        <textarea readOnly aria-label={`${doc.name}的失败详情`} rows={4}
          value={[doc.errorMessage || '未返回具体错误，请稍后重试或联系管理员', doc.stage && `处理阶段：${doc.stage}`, doc.ocrStatus && `OCR 状态：${doc.ocrStatus}`].filter(Boolean).join('\n')}
          className="w-full select-text rounded border border-red-200 bg-red-50 p-2 text-red-700 focus-visible:outline-2 focus-visible:outline-primary" />
      </div>
    </div>
  )
}

const AVATAR_COLORS = ['bg-blue-500', 'bg-emerald-500', 'bg-violet-500', 'bg-orange-500', 'bg-rose-500', 'bg-cyan-600']

export function Avatar({ name, size = 'md' }: { name: string; size?: 'sm' | 'md' }) {
  const idx = Array.from(name).reduce((acc, ch) => acc + ch.charCodeAt(0), 0) % AVATAR_COLORS.length
  return (
    <span
      className={`flex shrink-0 items-center justify-center rounded-full font-semibold text-white ${
        AVATAR_COLORS[idx]
      } ${size === 'sm' ? 'h-6 w-6 text-[11px]' : 'h-8 w-8 text-sm'}`}
    >
      {name.charAt(0)}
    </span>
  )
}

const FORMAT_STYLES: Record<string, string> = {
  PDF: 'bg-red-50 text-red-500 border-red-200',
  DOCX: 'bg-blue-50 text-blue-600 border-blue-200',
  XLSX: 'bg-emerald-50 text-emerald-600 border-emerald-200',
  MD: 'bg-violet-50 text-violet-600 border-violet-200',
}

export function FormatBadge({ format }: { format: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold ${
        FORMAT_STYLES[format] ?? 'bg-page text-ink-3 border-line'
      }`}
    >
      {format}
    </span>
  )
}

export function Switch({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean
  onChange?: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
        checked ? 'bg-primary' : 'bg-line'
      } ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
    >
      <span
        className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${
          checked ? 'left-[18px]' : 'left-0.5'
        }`}
      />
    </button>
  )
}

export function SectionTitle({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <h4 className="flex items-center gap-1.5 text-sm font-bold text-ink">
      <Icon size={15} className="text-primary" />
      {children}
    </h4>
  )
}
