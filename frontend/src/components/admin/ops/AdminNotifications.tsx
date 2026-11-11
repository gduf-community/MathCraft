import { Bell, CheckCheck, RefreshCw, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode, RefObject } from 'react'
import type { OpsClient, OpsNotification, OpsNotifications } from '../../../types/ops'
import { useToast } from '../../../store/ToastContext'
import { useOpsQuery } from './useOpsQuery'
import { trapOpsDialogFocus } from './OpsShared'

interface AdminNotificationsProps {
  client: OpsClient
  demo: boolean
  disabled: boolean
  onOpenAlert: (id: string) => void
}

type NotificationChange = { kind: 'read'; id: string | null } | { kind: 'delete'; id: string }

interface NotificationOperation {
  change: NotificationChange
  pending: string
  success: string
}

interface NotificationFeedback {
  text: string
  error: boolean
  retry?: NotificationOperation
}

/** 写入成功后立即更新快照，未读总数可包含列表窗口外的通知。 */
function applyNotificationChange(data: OpsNotifications, change: NotificationChange): OpsNotifications {
  if (change.kind === 'read' && change.id === null) {
    return { unread_count: 0, items: data.items.map(item => ({ ...item, read: true })) }
  }
  const wasUnread = data.items.some(item => item.id === change.id && !item.read)
  return {
    unread_count: Math.max(0, data.unread_count - (wasUnread ? 1 : 0)),
    items: change.kind === 'delete' ? data.items.filter(item => item.id !== change.id)
      : data.items.map(item => item.id === change.id ? { ...item, read: true } : item),
  }
}

/** 管理员独立通知入口，不依赖教师或学生的工作台状态。 */
export function AdminNotifications({ client, demo, disabled, onOpenAlert }: AdminNotificationsProps) {
  const load = useCallback((signal: AbortSignal) => client.listNotifications(signal), [client])
  const feed = useOpsQuery(load, true, 10000)
  const { showToast } = useToast()
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState<NotificationOperation | null>(null)
  const [feedback, setFeedback] = useState<NotificationFeedback | null>(null)
  const seen = useRef<Set<string> | null>(null)
  const mutation = useRef<NotificationOperation | null>(null)
  const mounted = useRef(false)
  const session = useRef(0)
  const button = useRef<HTMLButtonElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const restoreFocus = useRef<{ element: HTMLElement; session: number } | null>(null)
  const busy = pending !== null || feed.mutating

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; mutation.current = null }
  }, [])
  useEffect(() => {
    if (pending || !restoreFocus.current) return
    const target = restoreFocus.current
    restoreFocus.current = null
    if (target.session !== session.current || !dialog.current?.open) return
    const active = document.activeElement
    if (active && active !== document.body && active !== target.element) return
    if (target.element.isConnected && !target.element.hasAttribute('disabled')) {
      target.element.focus({ preventScroll: true })
    } else {
      dialog.current.querySelector<HTMLButtonElement>('[data-notification-close]')?.focus({ preventScroll: true })
    }
  }, [pending])
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
    session.current += 1
    setOpen(false)
  }
  async function mutate(operation: NotificationOperation) {
    if (mutation.current) return
    mutation.current = operation
    const operationSession = session.current
    const focused = document.activeElement
    const origin = focused instanceof HTMLElement && dialog.current?.contains(focused) ? focused : null
    setPending(operation)
    setFeedback(null)
    try {
      const { change } = operation
      const applied = await feed.mutate(signal => change.kind === 'delete'
        ? client.deleteNotification(change.id, signal)
        : client.markNotificationsRead(change.id === null ? [] : [change.id], signal),
      data => applyNotificationChange(data, change))
      if (applied && mounted.current && mutation.current === operation) {
        setFeedback({ text: operation.success, error: false })
        showToast(operation.success, 'success')
      }
    } catch (error: unknown) {
      if (mounted.current && mutation.current === operation) {
        const message = error instanceof Error ? error.message : '通知操作失败，请重试'
        setFeedback({ text: message, error: true, retry: operation })
        showToast(message, 'error')
      }
    } finally {
      if (mounted.current && mutation.current === operation) {
        if (origin) restoreFocus.current = { element: origin, session: operationSession }
        mutation.current = null
        setPending(null)
      }
    }
  }
  function visit(item: OpsNotification) {
    if (!item.ops_alert_id) return
    close()
    onOpenAlert(item.ops_alert_id)
  }

  return <>
    <button ref={button} type="button" aria-label="管理员通知" aria-haspopup="dialog"
      aria-expanded={open} aria-controls="admin-notification-dialog"
      disabled={disabled} onClick={() => { session.current += 1; setOpen(true) }}
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
    {open && <NotificationDialog onClose={close} dialog={dialog} trigger={button}>
      <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <h2 id="admin-notification-title" className="text-lg font-semibold">管理员通知</h2>
          <p className="mt-1 text-xs text-ink-2">{demo ? '合成演示 · 操作仅影响内存' : '站内通知'} · 已读不代表故障恢复</p>
        </div>
        <button type="button" onClick={close} aria-label="关闭通知" data-notification-close autoFocus
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-ink-2 hover:bg-page focus-visible:outline-2 focus-visible:outline-primary">
          <X size={20} aria-hidden="true" />
        </button>
      </header>
      <div aria-busy={busy} className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
        <button type="button" disabled={feed.loading || busy} onClick={feed.refresh}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm text-ink-2 hover:bg-page disabled:opacity-60">
          <RefreshCw size={16} aria-hidden="true" />{feed.loading ? '刷新中…' : '刷新通知'}
        </button>
        <button type="button" disabled={busy || !feed.data || feed.data.unread_count === 0}
          onClick={() => void mutate({ change: { kind: 'read', id: null },
            pending: '正在标记全部通知为已读…', success: '全部通知已标记为已读' })}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm text-primary hover:bg-primary-light disabled:opacity-50">
          <CheckCheck size={16} aria-hidden="true" />标记全部已读
        </button>
      </div>
      <div className="min-h-0 overflow-y-auto p-5">
        {pending && <p role="status" className="mb-3 rounded-lg bg-primary-light p-3 text-sm text-ink-2">{pending.pending}</p>}
        {feedback && <div role={feedback.error ? 'alert' : 'status'}
          className={`mb-3 rounded-lg p-3 text-sm ${feedback.error ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-800'}`}>
          <p>{feedback.text}</p>
          {feedback.retry && <button type="button" disabled={busy}
            onClick={() => { if (feedback.retry) void mutate(feedback.retry) }}
            className="mt-2 min-h-11 rounded-lg border border-current px-3 disabled:opacity-50">重试通知操作</button>}
        </div>}
        {feed.error && <p role="alert" className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">通知刷新失败：{feed.error}</p>}
        {feed.lastSuccess && <p className="mb-3 text-xs text-ink-2">最近成功更新：{new Date(feed.lastSuccess).toLocaleString('zh-CN', { hour12: false })}</p>}
        {feed.loading && !feed.data && <p role="status" className="py-8 text-center text-sm text-ink-2">正在加载通知…</p>}
        {feed.data?.items.length === 0 && <p className="py-8 text-center text-sm text-ink-2">暂无通知</p>}
        <ul aria-busy={busy} className="space-y-3">
          {feed.data?.items.map(item => <li key={item.id}
            className={`rounded-xl border p-4 ${item.read ? 'border-line' : 'border-primary/30 bg-primary-weak'}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-medium text-primary">{notificationLabel(item.kind)}{item.read ? ' · 已读' : ' · 未读'}</p>
                <h3 className="mt-1 break-words text-sm font-semibold">{item.title}</h3>
              </div>
              <button type="button" disabled={busy} aria-label={`删除通知：${item.title}`}
                onClick={() => void mutate({ change: { kind: 'delete', id: item.id },
                  pending: '正在删除通知…', success: '通知已删除' })}
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
                onClick={() => void mutate({ change: { kind: 'read', id: item.id },
                  pending: '正在标记通知为已读…', success: '通知已标记为已读' })}
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

function NotificationDialog({ children, onClose, dialog, trigger }: {
  children: ReactNode
  onClose: () => void
  dialog: RefObject<HTMLDialogElement | null>
  trigger: RefObject<HTMLButtonElement | null>
}) {
  useLayoutEffect(() => {
    const element = dialog.current
    const target = trigger.current
    const previousOverflow = document.body.style.overflow
    if (element && !element.open) element.showModal()
    document.body.style.overflow = 'hidden'
    return () => {
      const active = document.activeElement
      const shouldRestore = !active || active === document.body || !!element?.contains(active)
      element?.close()
      document.body.style.overflow = previousOverflow
      if (shouldRestore && target?.isConnected && !target.disabled) target.focus({ preventScroll: true })
    }
  }, [dialog, trigger])
  return <dialog ref={dialog} id="admin-notification-dialog" aria-labelledby="admin-notification-title"
    tabIndex={-1} onKeyDown={trapOpsDialogFocus}
    onCancel={event => { event.preventDefault(); onClose() }}
    className="fixed inset-0 m-auto max-h-[85dvh] w-[calc(100%-2rem)] max-w-xl overflow-hidden rounded-2xl border-0 bg-white p-0 text-ink shadow-2xl backdrop:bg-slate-900/45">
    <div className="flex max-h-[85dvh] flex-col">{children}</div>
  </dialog>
}
