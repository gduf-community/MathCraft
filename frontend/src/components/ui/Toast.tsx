import { useApp } from '../../store/AppContext'

/** 全局轻提示，顶部居中浮现；外层负责定位，内层只做入场动画，避免位移跳变 */
export default function Toast() {
  const { toast } = useApp()
  if (!toast) return null
  return (
    <div className="pointer-events-none fixed inset-x-0 top-16 z-50 flex justify-center">
      <div
        key={toast.id}
        className="rounded-lg bg-[#1f2937] px-4 py-2.5 text-sm text-white shadow-lg animate-toast-in"
      >
        {toast.text}
      </div>
    </div>
  )
}
