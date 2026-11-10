import { CircleCheck, CircleX, Info, X } from 'lucide-react'
import { useToast } from '../../store/ToastContext'

const STYLES = {
  success: 'border-emerald-700 bg-emerald-700 text-white',
  error: 'border-red-700 bg-red-700 text-white',
  info: 'border-slate-700 bg-slate-700 text-white',
} as const
const ICONS = { success: CircleCheck, error: CircleX, info: Info } as const

/** 全局轻提示，顶部居中浮现；外层负责定位，内层只做入场动画，避免位移跳变 */
export default function Toast() {
  const { toast, dismissToast } = useToast()
  const Icon = toast ? ICONS[toast.variant] : Info
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
        className={`pointer-events-auto flex max-w-xl items-center gap-3 rounded-lg border py-2 pl-4 pr-2 text-sm shadow-lg motion-safe:animate-toast-in ${STYLES[toast.variant]}`}
      >
        <Icon size={20} className="shrink-0" aria-hidden="true" />
        <span className="min-w-0 whitespace-pre-wrap break-words">{toast.text}</span>
        <button type="button" onClick={dismissToast} aria-label="关闭提示"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md hover:bg-white/15 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white">
          <X size={18} aria-hidden="true" />
        </button>
      </div>}
    </div>
  )
}
