import { useApp } from '../../store/AppContext'

/** 全局轻提示，顶部居中浮现 */
export default function Toast() {
  const { toast } = useApp()
  if (!toast) return null
  return (
    <div
      key={toast.id}
      className="fixed left-1/2 top-16 z-50 -translate-x-1/2 rounded-lg bg-[#1f2937] px-4 py-2.5 text-sm text-white shadow-lg animate-toast-in"
    >
      {toast.text}
    </div>
  )
}
