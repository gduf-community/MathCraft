/** 通用确认弹窗：删除题库、退出题库、题库转让等操作确认 */
import { AlertTriangle } from 'lucide-react'

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
  onConfirm: () => void
  onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45" onClick={onClose}>
      <div
        className="w-[380px] rounded-2xl bg-white p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <span
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
              danger ? 'bg-red-50 text-red-500' : 'bg-primary-light text-primary'
            }`}
          >
            <AlertTriangle size={18} />
          </span>
          <div>
            <h3 className="text-[15px] font-bold text-ink">{title}</h3>
            <p className="mt-1.5 text-sm leading-6 text-ink-2">{message}</p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:bg-page"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => {
              onConfirm()
              onClose()
            }}
            className={`rounded-lg px-4 py-2 text-sm font-semibold text-white transition-colors ${
              danger ? 'bg-red-500 hover:bg-red-600' : 'bg-primary hover:bg-[#1a5fe6]'
            }`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
