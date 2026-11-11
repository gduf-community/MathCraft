import { Bell, CheckCheck, RefreshCw, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { OpsClient, OpsNotification } from '../../../types/ops'
import { useToast } from '../../../store/ToastContext'
import { useOpsQuery } from './useOpsQuery'

interface AdminNotificationsProps {
  client: OpsClient
  demo: boolean
  disabled: boolean
  onOpenAlert: (id: string) => void
}

/** 管理员独立通知入口，不依赖教师或学生的工作台状态。 */
export function AdminNotifications({ client, demo, disabled, onOpenAlert }: AdminNotificationsProps) {
  const load = useCallback((signal: AbortSignal) => client.listNotifications(signal), [client])
  const feed = useOpsQuery(load, true, 10000)
  const { showToast } = useToast()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<{ text: string; error: boolean } | null>(null)
  const seen = useRef<Set<string> | null>(null)
  const mutation = useRef<AbortController | null>(null)
  const button = useRef<HTMLButtonElement>(null)

  useEffect(() => () => { mutation.current?.abort() }, [])
  useEffect(() => {
    if (!feed.data) return
    const fresh = feed.data.items.filter(item => !item.read && item.kind.startsWith('ops_')
      && seen.current !== null && !seen.current.has(item.id))
    if (fresh.length > 0) showToast(`收到 ${fresh.length} 条新的运维通知`, 'info')
    const known = seen.current ?? new Set<string>()
    for (const item of feed.data.items) known.add(item.id)
    seen.current = known
  }, [feed.data, showToast])

  const close = () => {
    setOpen(false)
    button.current?.focus()
  }
  async function mutate(action: (signal: AbortSignal) => Promise<void>, success: string) {
    if (mutation.current) return
    const controller = new AbortController()
    mutation.current = controller
    setBusy(true)
    setFeedback(null)
    try {
      await action(controller.signal)
      if (!controller.signal.aborted) {
        setFeedback({ text: success, error: false })
        showToast(success, 'success')
        feed.refresh()
      }
    } catch (error: unknown) {
      if (!controller.signal.aborted) {
        const message = error instanceof Error ? error.message : '通知操作失败，请重试'
        setFeedback({ text: message, error: true })
        showToast(message, 'error')
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false)
      mutation.current = null
    }
  }
  function visit(item: OpsNotification) {
    if (!item.ops_alert_id) return
    close()
    onOpenAlert(item.ops_alert_id)
  }

  return <>
    <button ref={button} type="button" aria-label="管理员通知" aria-haspopup="dialog"
      disabled={disabled} onClick={() => setOpen(true)}
      className="relative inline-flex min-h-11 items-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink-2 transition-colors hover:bg-primary-light focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-60">
      <Bell size={18} aria-hidden="true" />
      <span>通知</span>
      {feed.data && feed.data.unread_count > 0 && <span
        className="rounded-full bg-red-600 px-1.5 py-0.5 text-xs font-semibold text-white"
        aria-label={`${feed.data.unread_count} 条未读通知`}>
        {feed.data.unread_count > 99 ? '99+' : feed.data.unread_count}
      </span>}
      {feed.error && <span className="h-2 w-2 rounded-full bg-amber-600" aria-label="通知刷新失败" />}
    </button>
    {open && <NotificationDialog onClose={close}>
      <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <h2 id="admin-notification-title" className="text-lg font-semibold">管理员通知</h2>
          <p className="mt-1 text-xs text-ink-2">{demo ? '合成演示 · 操作仅影响内存' : '站内通知'} · 已读不代表故障恢复</p>
        </div>
        <button type="button" onClick={close} aria-label="关闭通知"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-ink-2 hover:bg-page">
          <X size={20} aria-hidden="true" />
        </button>
      </header>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
        <button type="button" disabled={feed.loading} onClick={feed.refresh}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm text-ink-2 hover:bg-page disabled:opacity-60">
          <RefreshCw size={16} aria-hidden="true" />{feed.loading ? '刷新中…' : '刷新通知'}
        </button>
        <button type="button" disabled={busy || !feed.data || feed.data.unread_count === 0}
          onClick={() => void mutate(signal => client.markNotificationsRead([], signal), '全部通知已标记为已读')}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm text-primary hover:bg-primary-light disabled:opacity-50">
          <CheckCheck size={16} aria-hidden="true" />标记全部已读
        </button>
      </div>
      <div className="min-h-0 overflow-y-auto p-5">
        {feedback && <p role={feedback.error ? 'alert' : 'status'}
          className={`mb-3 rounded-lg p-3 text-sm ${feedback.error ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-800'}`}>
          {feedback.text}
        </p>}
        {feed.error && <p role="alert" className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">通知刷新失败：{feed.error}</p>}
        {feed.lastSuccess && <p className="mb-3 text-xs text-ink-2">最近成功更新：{new Date(feed.lastSuccess).toLocaleString('zh-CN', { hour12: false })}</p>}
        {feed.loading && !feed.data && <p role="status" className="py-8 text-center text-sm text-ink-2">正在加载通知…</p>}
        {feed.data?.items.length === 0 && <p className="py-8 text-center text-sm text-ink-2">暂无通知</p>}
        <ul className="space-y-3">
          {feed.data?.items.map(item => <li key={item.id}
            className={`rounded-xl border p-4 ${item.read ? 'border-line' : 'border-primary/30 bg-primary-weak'}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-medium text-primary">{notificationLabel(item.kind)}{item.read ? ' · 已读' : ' · 未读'}</p>
                <h3 className="mt-1 break-words text-sm font-semibold">{item.title}</h3>
              </div>
              <button type="button" disabled={busy} aria-label={`删除通知：${item.title}`}
                onClick={() => void mutate(signal => client.deleteNotification(item.id, signal), '通知已删除')}
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-ink-2 hover:bg-red-50 hover:text-red-700 disabled:opacity-50">
                <Trash2 size={16} aria-hidden="true" />
              </button>
            </div>
            <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-ink-2">{item.body}</p>
            <p className="mt-2 text-xs text-ink-2">{new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })}
              {item.ops_episode_no != null && ` · 第 ${item.ops_episode_no} 轮`}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {item.ops_alert_id && <button type="button" onClick={() => visit(item)} disabled={busy}
                className="min-h-11 rounded-lg px-3 text-sm font-medium text-primary hover:bg-primary-light disabled:opacity-50">查看异常轮次</button>}
              {!item.read && <button type="button" disabled={busy}
                onClick={() => void mutate(signal => client.markNotificationsRead([item.id], signal), '通知已标记为已读')}
                className="min-h-11 rounded-lg px-3 text-sm text-ink-2 hover:bg-page disabled:opacity-50">标记已读</button>}
            </div>
          </li>)}
        </ul>
      </div>
    </NotificationDialog>}
  </>
}

function notificationLabel(kind: OpsNotification['kind']): string {
  switch (kind) {
    case 'ops_alert_trigger': return '异常触发'
    case 'ops_alert_reminder': return '持续故障提醒'
    case 'ops_alert_recovery': return '异常恢复'
    case 'bank_failed': return '文档处理失败'
    default: return '文档处理完成'
  }
}

function NotificationDialog({ children, onClose }: {
  children: ReactNode
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current
    const previousFocus = document.activeElement
    const previousOverflow = document.body.style.overflow
    element?.showModal()
    document.body.style.overflow = 'hidden'
    return () => {
      element?.close()
      document.body.style.overflow = previousOverflow
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus()
    }
  }, [])
  return <dialog ref={dialog} aria-labelledby="admin-notification-title"
    onCancel={event => { event.preventDefault(); onClose() }}
    className="fixed inset-0 m-auto max-h-[85dvh] w-[calc(100%-2rem)] max-w-xl overflow-hidden rounded-2xl border-0 bg-white p-0 text-ink shadow-2xl backdrop:bg-slate-900/45">
    <div className="flex max-h-[85dvh] flex-col">{children}</div>
  </dialog>
}
