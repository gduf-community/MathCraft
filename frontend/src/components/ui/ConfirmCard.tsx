import { CheckCircle2, XCircle } from 'lucide-react'
import type { ChatConfirm } from '../../types'

/** 数据管理高危操作确认卡：展示影响范围，接受执行 / 拒绝取消 */
export default function ConfirmCard({
  confirm,
  busy,
  onAccept,
  onReject,
}: {
  confirm: ChatConfirm
  busy: boolean
  onAccept: () => void
  onReject: () => void
}) {
  const isDelete = confirm.action === 'delete'
  return (
    <div className="flex justify-start">
      <div className="ml-10 w-[min(560px,90%)] rounded-2xl rounded-tl-sm border border-amber-300 bg-amber-50/70 p-4">
        <div className="flex items-center gap-2">
          <span className={`rounded px-1.5 py-0.5 text-xs font-semibold text-white ${isDelete ? 'bg-red-500' : 'bg-primary'}`}>
            {isDelete ? '删除操作' : '改名操作'}
          </span>
          <span className="text-sm font-semibold text-ink">
            将{isDelete ? '删除' : '重命名'} {confirm.affected} 条{confirm.entity_label}
          </span>
        </div>
        {confirm.explanation && <p className="mt-1.5 text-xs text-ink-2">{confirm.explanation}</p>}
        <ul className="mt-2 space-y-1 rounded-lg bg-white/80 p-2.5 text-xs leading-5 text-ink-2">
          {confirm.samples.map((s, i) => (
            <li key={i} className="truncate">{s}</li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-ink-3">该操作需要你确认后才会执行。</p>
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={onReject}
            className="flex items-center gap-1 rounded-lg border border-line bg-white px-3.5 py-1.5 text-sm text-ink-2 transition-colors hover:bg-page disabled:opacity-45"
          >
            <XCircle size={14} />
            拒绝
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onAccept}
            className={`flex items-center gap-1 rounded-lg px-3.5 py-1.5 text-sm font-medium text-white transition-all active:scale-[0.97] disabled:opacity-45 ${
              isDelete ? 'bg-red-500 hover:bg-red-500/90' : 'bg-primary hover:bg-[#1a5fe6]'
            }`}
          >
            <CheckCircle2 size={14} />
            {busy ? '执行中…' : '接受并执行'}
          </button>
        </div>
      </div>
    </div>
  )
}
