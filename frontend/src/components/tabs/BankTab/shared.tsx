/** 题库管理页共享小组件：头像、格式徽标、权限开关 */
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

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
