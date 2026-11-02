import { X } from 'lucide-react'
import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

interface ConfigurationDialogProps {
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
  busy?: boolean
  onClose: () => void
}

/** 业务方统一处理取消、关闭与 Esc；遮罩不触发关闭。 */
export function ConfigurationDialog({ title, description, children, footer, busy = false, onClose }: ConfigurationDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const id = useId()

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog.showModal()
    const firstField = dialog.querySelector<HTMLElement>('input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled)')
    firstField?.focus({ preventScroll: true })
    return () => {
      dialog.close()
      document.body.style.overflow = previousOverflow
      if (trigger?.isConnected) trigger.focus({ preventScroll: true })
    }
  }, [])

  return createPortal(<dialog
    ref={dialogRef}
    className="configuration-dialog"
    aria-labelledby={`${id}-title`}
    aria-describedby={description ? `${id}-description` : undefined}
    aria-modal="true"
    tabIndex={-1}
    aria-busy={busy}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }}
    onKeyDown={(event) => {
      if (event.key !== 'Tab') return
      const dialog = event.currentTarget
      const controls = Array.from(dialog.querySelectorAll<HTMLElement>('button, a[href], input:not([type="hidden"]), select, textarea, summary, [tabindex]'))
        .filter((element) => element.tabIndex >= 0 && !element.matches(':disabled') && element.getClientRects().length > 0)
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (!first) {
        event.preventDefault()
        dialog.focus()
      } else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }}
  >
    <header className="configuration-dialog-header">
      <div className="min-w-0">
        <h2 id={`${id}-title`} className="break-words text-lg font-semibold text-ink">{title}</h2>
        {description && <p id={`${id}-description`} className="mt-1 text-sm leading-6 text-ink-2">{description}</p>}
      </div>
      <button type="button" className="configuration-dialog-close" aria-label="关闭配置面板" disabled={busy} onClick={onClose}>
        <X size={20} aria-hidden="true" />
      </button>
    </header>
    <div className="configuration-dialog-content">{children}</div>
    {footer && <footer className="configuration-dialog-footer">{footer}</footer>}
  </dialog>, document.body)
}
