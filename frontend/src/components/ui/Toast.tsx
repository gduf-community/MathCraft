import { useToast } from '../../store/ToastContext'
import type { ToastVariant } from '../../store/ToastContext'

/** 变体对应的浅淡柔和配色：整体轻量，不带关闭按钮，超时自动消失 */
const VARIANT_STYLES: Record<ToastVariant, string> = {
  info: 'border-primary/15 bg-primary-weak/95 text-ink',
  success: 'border-emerald-200/80 bg-emerald-50/95 text-emerald-700',
  error: 'border-red-200/80 bg-red-50/95 text-red-500',
}

/** 全局轻提示，顶部居中浮现；外层负责定位，内层只做入场动画，避免位移跳变 */
export default function Toast() {
  const { toast } = useToast()
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
        className={`pointer-events-auto max-w-xl rounded-xl border px-4 py-2.5 text-sm shadow-[0_8px_24px_rgba(30,90,180,0.08)] backdrop-blur-sm motion-safe:animate-toast-in ${VARIANT_STYLES[toast.variant]}`}
      >
        <span className="min-w-0 whitespace-pre-wrap break-words">{toast.text}</span>
      </div>}
    </div>
  )
}
