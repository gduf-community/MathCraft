import { useApp } from '../../store/AppContext'

/** 全局轻提示，顶部居中浮现；支持一个可选的操作按钮（如「撤销」） */
export default function Toast() {
  const { toast, dismissToast } = useApp()
  if (!toast) return null
  return (
    <div
      key={toast.id}
      className="fixed left-1/2 top-16 z-50 flex -translate-x-1/2 items-center gap-3 rounded-lg bg-[#1f2937] px-4 py-2.5 text-sm text-white shadow-lg animate-toast-in"
      role="status"
    >
      <span>{toast.text}</span>
      {toast.actionLabel && (
        <button
          type="button"
          onClick={() => {
            toast.onAction?.()
            dismissToast()
          }}
          className="shrink-0 font-semibold text-[#9ec3ff] transition-colors hover:text-[#cfe0ff]"
        >
          {toast.actionLabel}
        </button>
      )}
    </div>
  )
}
