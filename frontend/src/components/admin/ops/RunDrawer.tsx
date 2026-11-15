import { useCallback, useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import type { OpsClient } from '../../../types/ops'
import {
  OpsBadge, OpsCard, OpsFacts, OpsFeedback, OpsMetaNotice,
  opsButtonClass, opsLabel, opsNumber, opsTime, trapOpsDialogFocus,
} from './OpsShared'
import { useOpsQuery } from './useOpsQuery'

interface RunDrawerProps { client: OpsClient; runId: string; onClose: () => void }
/** 原生模态框隔离背景；关闭后恢复原页面焦点与滚动。 */
export function RunDrawer({ client, runId, onClose }: RunDrawerProps) {
  const dialog = useRef<HTMLDialogElement>(null), closeButton = useRef<HTMLButtonElement>(null)
  const titleId = useId(), descriptionId = useId()
  const load = useCallback((signal: AbortSignal) => client.getRun(runId, signal), [client, runId])
  const result = useOpsQuery(load)
  const run = result.data?.run
  useEffect(() => {
    const element = dialog.current
    if (!element) return
    const previousFocus = document.activeElement, previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    element.showModal(); closeButton.current?.focus({ preventScroll: true })
    return () => {
      element.close(); document.body.style.overflow = previousOverflow
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true })
    }
  }, [])
  return createPortal(<dialog ref={dialog} aria-labelledby={titleId} aria-describedby={descriptionId}
    aria-modal="true" tabIndex={-1} onKeyDown={trapOpsDialogFocus}
    onCancel={event => { event.preventDefault(); onClose() }}
    className="fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-none w-full max-w-2xl border-l border-line bg-page p-0 text-ink shadow-xl backdrop:bg-ink/40">
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-start justify-between gap-3 border-b border-line bg-white p-4 sm:p-5">
        <div className="min-w-0"><h2 id={titleId} className="text-lg font-semibold">运行详情</h2>
          <p className="mt-1 break-all text-sm text-ink-2">{runId}</p>
          <p id={descriptionId} className="mt-1 text-xs text-ink-2">只读运行摘要，按 Escape 关闭。</p>
        </div>
        <button ref={closeButton} type="button" onClick={onClose} className={opsButtonClass} aria-label="关闭运行详情">关闭</button>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-ink-2">每 15 秒刷新；页面隐藏时暂停。</p>
          <button type="button" className={opsButtonClass} onClick={result.refresh} disabled={result.loading}>刷新详情</button>
        </div>
        <OpsFeedback {...result} hasData={!!result.data} onRetry={result.refresh} />
        <OpsMetaNotice meta={result.data} lastSuccess={result.lastSuccess} />
        {run && <>
          <OpsCard title="运行结果" action={<OpsBadge value={run.status} />}>
            <OpsFacts items={[
              ['请求数量', opsNumber(run.requested_count)], ['已保存数量', opsNumber(run.delivered_count)],
              ['错误分类', run.error_code ? `${opsLabel(run.error_code)}（${run.error_code}）` : '无错误分类'],
            ]} />
            <p className="mt-3 text-xs text-ink-2">批次已保存只表示保存事实，不表示题量达标或数学质量通过。未知数量保留未知。</p>
          </OpsCard>
          <OpsCard title="业务关联"><OpsFacts items={[
            ['归属账号', run.owner_user_id], ['入口', opsLabel(run.entrypoint)],
            ['会话 ID', run.session_id ?? '未知／不适用'], ['任务 ID', run.task_id ?? '未知／不适用'],
            ['题库 ID', run.bank_id ?? '未知'], ['文档 ID', run.document_id ?? '未知'],
            ['批次 ID', run.batch_id ?? '尚未确认'],
          ]} /></OpsCard>
          <OpsCard title="运行时间"><OpsFacts items={[
            ['受理时间', opsTime(run.accepted_at)], ['开始时间', opsTime(run.started_at)],
            ['结束时间', opsTime(run.finished_at)], ['最后观测时间', opsTime(run.last_observed_at)],
          ]} /><p className="mt-3 text-xs text-ink-2">最后观测时间不表示心跳；时间缺失不据此推断失败。</p></OpsCard>
        </>}
      </div>
    </div>
  </dialog>, document.body)
}
