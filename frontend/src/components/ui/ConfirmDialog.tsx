/** 通用确认弹窗：删除题库、退出题库、题库转让等操作确认 */
import { AlertTriangle, Loader2 } from 'lucide-react'
import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export default function ConfirmDialog({
  title,
  message,
  confirmText = '确定',
  danger = true,
  onConfirm,
  onClose,
}: {
  title: string
  message: string
  confirmText?: string
  danger?: boolean
  onConfirm: () => Promise<void> | void
  onClose: () => void
}) {
  const titleId = useId()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const confirmLock = useRef(false)
  const close = () => {
    if (!confirmLock.current) onClose()
  }
  const confirm = async () => {
    if (confirmLock.current) return
    confirmLock.current = true
    setPending(true)
    setError('')
    try {
      await onConfirm()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败，请重试')
    } finally {
      confirmLock.current = false
      setPending(false)
    }
  }
  // portal 挂到 body：脱离 main（z-10）的堆叠上下文，保证遮罩盖住右侧参数栏
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/60 p-4 backdrop-blur-[2px]" onClick={close}
      onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); close() } }}>
      <div
        role="dialog" aria-modal="true" aria-labelledby={titleId} aria-busy={pending}
        className="w-[380px] max-w-full rounded-2xl bg-white p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <span
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
              danger ? 'bg-red-50 text-red-500' : 'bg-primary-light text-primary'
            }`}
          >
            <AlertTriangle size={18} aria-hidden="true" />
          </span>
          <div>
            <h3 id={titleId} className="text-[15px] font-bold text-ink">{title}</h3>
            <p className="mt-1.5 text-sm leading-6 text-ink-2">{message}</p>
          </div>
        </div>
        {error && <p role="alert" className="mt-3 break-words rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <div className="mt-5 flex justify-end gap-2.5">
          <button
            type="button"
            autoFocus
            onClick={close}
            disabled={pending}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:bg-page disabled:cursor-not-allowed disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void confirm()}
            disabled={pending}
            className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold text-white transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              danger ? 'bg-red-500 hover:bg-red-600' : 'bg-primary hover:bg-[#1a5fe6]'
            }`}
          >
            {pending && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            {pending ? '处理中…' : confirmText}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
