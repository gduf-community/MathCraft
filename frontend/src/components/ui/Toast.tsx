import { X } from 'lucide-react'
import { useToast } from '../../store/ToastContext'

/** 全局轻提示，顶部居中浮现；外层负责定位，内层只做入场动画，避免位移跳变 */
export default function Toast() {
  const { toast, dismissToast } = useToast()
  return (
    <div className="pointer-events-none fixed inset-x-0 top-16 z-[100] flex justify-center px-4">
      <div role="status" aria-live="polite" aria-atomic="true">
        {toast && toast.variant !== 'error' && <span className="sr-only" key={toast.id}>{toast.text}</span>}
      </div>
      <div role="alert" aria-live="assertive" aria-atomic="true">
        {toast?.variant === 'error' && <span className="sr-only" key={toast.id}>{toast.text}</span>}
      </div>
      {toast && <div
        key={toast.id}
        className="pointer-events-auto flex max-w-xl items-center gap-2 rounded-lg bg-ink px-4 py-2.5 text-sm text-white shadow-lg motion-safe:animate-toast-in"
      >
        <span className="min-w-0 whitespace-pre-wrap break-words">{toast.text}</span>
        <button type="button" onClick={dismissToast} aria-label="关闭提示"
          className="-my-2.5 -mr-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-md hover:bg-white/15 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white">
          <X size={18} aria-hidden="true" />
        </button>
      </div>}
    </div>
  )
}
