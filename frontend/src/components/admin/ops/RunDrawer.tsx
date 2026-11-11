import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useToast } from '../../../store/ToastContext'
import type { OpsAlert, OpsClient, OpsPage, OpsQuery, OpsRun, OpsRunDetail } from '../../../types/ops'
import {
  OpsBadge, OpsCard, OpsFacts, OpsFeedback, OpsMetaNotice, OpsReasons, OpsRunStates,
  opsButtonClass, opsDuration, opsLabel, opsNumber, opsPercent, opsPrimaryClass, opsTime, opsAlertRuleLabel, trapOpsDialogFocus,
} from './OpsShared'
import { useOpsQuery } from './useOpsQuery'
import { EffectiveConfig, ReviewVersions } from './OpsExtensions'

interface RunDrawerProps {
  client: OpsClient
  runId: string
  onClose: () => void
  onOpenAlerts: (query: OpsQuery) => void
  demo: boolean
}

export function RunDrawer(props: RunDrawerProps) {
  return <RunDrawerContent key={props.runId} {...props} />
}

/** 原生模态对话框使背景 inert；关闭后恢复原页面焦点与滚动。 */
function RunDrawerContent({ client, runId, onClose, onOpenAlerts, demo }: RunDrawerProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const descriptionId = useId()
  const { showToast } = useToast()
  const [traceNotice, setTraceNotice] = useState('')
  const [traceBusy, setTraceBusy] = useState(false)
  const tracePending = useRef(false)
  const mounted = useRef(false)
  const load = useCallback((signal: AbortSignal) => client.getRun(runId, signal), [client, runId])
  const result = useOpsQuery<OpsRunDetail>(load)
  const run = result.data?.run

  useEffect(() => {
    mounted.current = true
    const element = dialog.current
    if (!element) return
    const previousFocus = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    element.showModal()
    closeButton.current?.focus({ preventScroll: true })
    return () => {
      mounted.current = false
      element.close()
      document.body.style.overflow = previousOverflow
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
        previousFocus.focus({ preventScroll: true })
      }
    }
  }, [])

  async function openTrace() {
    if (!run || tracePending.current) return
    tracePending.current = true
    setTraceBusy(true)
    try {
      setTraceNotice('')
      const access = await client.openTrace(run.trace.viewer_path ?? '')
      if (mounted.current) {
        setTraceNotice(access.message)
        showToast(access.message, 'info')
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : '无法打开追踪，请刷新后重试。'
      if (mounted.current) {
        setTraceNotice(message)
        showToast(message, 'error')
      }
    } finally {
      tracePending.current = false
      if (mounted.current) setTraceBusy(false)
    }
  }

  return createPortal(<dialog ref={dialog} aria-labelledby={titleId} aria-describedby={descriptionId}
    aria-modal="true" tabIndex={-1} onKeyDown={trapOpsDialogFocus}
    onCancel={event => { event.preventDefault(); onClose() }}
    className="fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-none w-full max-w-2xl border-l border-line bg-page p-0 text-ink shadow-xl backdrop:bg-ink/40">
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-start justify-between gap-3 border-b border-line bg-white p-4 sm:p-5">
        <div className="min-w-0">
          <h2 id={titleId} className="text-lg font-semibold">运行详情</h2>
          <p className="mt-1 break-all text-sm text-ink-2">{runId}</p>
          <p id={descriptionId} className="mt-1 text-xs text-ink-2">只读摘要；执行、质量、追踪独立判断。按 Escape 关闭。</p>
        </div>
        <button ref={closeButton} type="button" onClick={onClose} className={`${opsButtonClass} shrink-0`} aria-label="关闭运行详情">关闭</button>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain p-4 sm:p-5">
        {traceNotice && <div role="status" className="sticky top-0 z-10 rounded-lg border border-line bg-primary-light p-3 text-sm shadow-sm">
          {traceNotice}
        </div>}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-ink-2">每 15 秒刷新；页面隐藏时暂停。</p>
          <button type="button" className={opsButtonClass} onClick={result.refresh} disabled={result.loading}>刷新详情</button>
        </div>
        <OpsFeedback loading={result.loading} error={result.error} hasData={!!result.data} onRetry={result.refresh} retryLabel="重新加载运行详情" />
        <OpsMetaNotice meta={result.data} lastSuccess={result.lastSuccess} />
        {run && <>
          <OpsCard title="执行、交付质量与追踪">
            <OpsRunStates run={run} />
            <p className="mt-3 text-xs text-ink-2">正常结束仅指执行体确认结束；规则达标不代表数学内容正确；导出受理不证明追踪已落库。</p>
            <div className="mt-4 space-y-3">
              <div><p className="mb-1 text-sm text-ink-2">执行原因</p>
                {run.execution_reason_code ? <OpsReasons codes={[run.execution_reason_code]} /> : <p className="text-sm">无异常原因／尚未产生</p>}</div>
              <div><p className="mb-1 text-sm text-ink-2">质量原因</p><OpsReasons codes={run.quality.reason_codes} /></div>
            </div>
          </OpsCard>
          <RunIdentity run={run} />
          <RunObservation run={run} />
          <RunQuality run={run} />
          {result.data && <ReviewVersions detail={result.data} />}
          <OpsCard title="重出与降级">
            <OpsFacts items={[
              ['已启动逻辑重出尝试', opsNumber(run.regeneration.attempt_count)],
              ['尝试成功', opsNumber(run.regeneration.succeeded_count)],
              ['尝试失败', opsNumber(run.regeneration.failed_count)],
              ['尝试尚未结束', opsNumber(run.regeneration.in_flight_count)],
              ['已结束尝试耗时之和', opsDuration(run.regeneration.total_attempt_ms)],
              ['是否发生降级', run.degradation.occurred == null ? '未知／未采集' : run.degradation.occurred ? '是（有明确降级证据）' : '否（采集完整且无降级）'],
            ]} />
            <div className="mt-3"><p className="mb-2 text-sm font-medium">频繁重出阈值</p><EffectiveConfig config={result.data?.regeneration_config} /></div>
            <div className="mt-3"><OpsReasons codes={run.degradation.reason_codes} /></div>
            <p className="mt-3 text-xs text-ink-2">传输重试不算逻辑重出；重出成功不等于最终交付保留。并行尝试耗时可重叠，不能相加当作运行墙钟耗时。</p>
          </OpsCard>
          <TraceSummary run={run} onOpen={() => void openTrace()} demo={demo} busy={traceBusy} />
          <OpsCard title="执行阶段（可重复、可并行）">
            <p className="mb-3 text-xs text-ink-2">按服务端提供的阶段展示；父阶段与子阶段、并行阶段耗时可能重叠，不相加推算运行总耗时。</p>
            {result.data?.stages == null ? <p className="text-sm text-ink-2">阶段时间线未采集，不能补造链路。</p>
              : result.data.stages.length === 0 ? <p className="text-sm text-ink-2">已确认阶段集合为空。</p>
                : <ol className="space-y-3">{result.data.stages.map(stage => <li key={stage.stage_id} className="rounded-lg border border-line bg-page p-3">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-sm font-medium">{opsLabel(stage.name)} · 尝试 {stage.attempt_index}</h4>
                    <OpsBadge value={stage.status} />
                  </div>
                  <OpsFacts items={[
                    ['阶段 ID', stage.stage_id], ['父阶段 ID', stage.parent_stage_id ?? '无父阶段'],
                    ['开始', opsTime(stage.started_at)], ['结束', opsTime(stage.finished_at)],
                    ['阶段耗时', opsDuration(stage.elapsed_ms)],
                  ]} />
                  {stage.reason_code && <div className="mt-3"><OpsReasons codes={[stage.reason_code]} /></div>}
                </li>)}</ol>}
          </OpsCard>
          <RelatedAlerts client={client} runId={runId} onOpenAlerts={onOpenAlerts} />
        </>}
      </div>
    </div>
  </dialog>, document.body)
}

function RunIdentity({ run }: { run: OpsRun }) {
  return <OpsCard title="运行关联、采集与耗时" action={<OpsBadge value={run.collection_state} />}>
    <OpsFacts items={[
      ['归属账号', run.owner_user_id], ['入口', opsLabel(run.entrypoint)],
      ['会话', run.session_id ?? '不适用／尚未绑定'], ['成果批次', run.batch_id ?? '尚未绑定／未产生'],
      ['运行摘要版本', opsNumber(run.revision)], ['当前阶段', opsLabel(run.current_stage)],
      ['受理', opsTime(run.accepted_at)], ['执行开始', opsTime(run.started_at)],
      ['执行结束', opsTime(run.finished_at)], ['摘要更新', opsTime(run.updated_at)],
      ['受理至开始等待', opsDuration(run.wait_ms)], ['最终运行墙钟耗时', opsDuration(run.elapsed_ms)],
      ['运行至今（非最终耗时）', opsDuration(run.running_age_ms)],
    ]} />
    {run.unknown_fields.length > 0 && <div className="mt-3 rounded-lg bg-star/5 p-3 text-sm">
      <p className="font-medium">以下字段缺少采集证据</p>
      <ul className="mt-1 space-y-1">{run.unknown_fields.map(field => <li key={field} className="break-all font-mono text-xs">{field}</li>)}</ul>
    </div>}
  </OpsCard>
}

function RunObservation({ run }: { run: OpsRun }) {
  return <OpsCard title="运行观察（不修改业务终态）">
    <OpsFacts items={[
      ['最近服务端心跳', opsTime(run.heartbeat_at)],
      ['最近监测器评估', opsTime(run.observation_checked_at)],
    ]} />
    <div className="mt-3"><OpsReasons codes={run.observation_flags} /></div>
    {run.observation_unknown_reason && <div className="mt-3"><OpsReasons codes={[run.observation_unknown_reason]} /></div>}
    <p className="mt-3 text-xs text-ink-2">运行心跳与监测器新鲜度分别判断。空标记仅表示有效评估未命中；监测失联、长时间运行、锁过期或追踪缺失均不能证明执行已失败或结束。</p>
  </OpsCard>
}

function RunQuality({ run }: { run: OpsRun }) {
  return <OpsCard title="最终交付题量与审核覆盖">
    <OpsFacts items={[
      ['目标题量', opsNumber(run.counts.target_count)], ['当前最终可交付题量', opsNumber(run.counts.actual_count)],
      ['题量状态', opsLabel(run.counts.quantity_status)],
      ['是否要求审核', run.review.required == null ? '未知' : run.review.required ? '要求' : '明确不要求'],
      ['最终版本审核状态', opsLabel(run.review.status)],
      ['应审核题数', opsNumber(run.review.eligible_count)],
      ['有明确审核结论题数', opsNumber(run.review.covered_count)],
      ['明确审核通过题数', opsNumber(run.review.passed_count)],
      ['明确跳审题数', opsNumber(run.review.skipped_count)],
      ['审核证据未知／未完成题数', opsNumber(run.review.unknown_count)],
      ['审核覆盖率', opsPercent(run.review.coverage_rate)],
      ['覆盖率空值原因', run.review.coverage_reason ? opsLabel(run.review.coverage_reason) : '无空值原因'],
    ]} />
    <p className="mt-3 text-xs text-ink-2">题量按去重后、已持久化的最终交付集合计数；审核只计算最终版本。unknown 放行不算覆盖，不要求审核或零成果时覆盖率不补 0%。</p>
  </OpsCard>
}

function TraceSummary({ run, onOpen, demo, busy }: { run: OpsRun; onOpen: () => void; demo: boolean; busy: boolean }) {
  const trace = run.trace
  return <OpsCard title="详细追踪（独立于执行与质量）" action={<OpsBadge value={trace.availability} />}>
    <OpsFacts items={[
      ['SDK 根 Trace ID', trace.sdk_trace_id ?? '未知／尚未产生'],
      ['Phoenix Trace ID', trace.phoenix_trace_id ?? '映射未确认'],
      ['会话分组 ID', trace.group_id ?? '未知'], ['导出状态', opsLabel(trace.export_status)],
      ['完整性', trace.complete == null ? '未知／未核对' : trace.complete ? '已核对齐全' : '部分追踪（缺少预期 span）'],
      ['按具体标识核验时间', opsTime(trace.verified_at)], ['正文逻辑到期', opsTime(trace.expires_at)],
    ]} />
    {trace.reason_code && <div className="mt-3"><OpsReasons codes={[trace.reason_code]} /></div>}
    <p className="mt-3 text-xs text-ink-2">submitted 仅表示导出端点受理。Phoenix 在线不证明本条追踪可查看；过期、无权、未采集与查询故障分别保留其状态。</p>
    <details className="mt-3 rounded-lg border border-line p-3">
      <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium text-primary">查看正文访问说明</summary>
      <p className="mt-2 text-sm text-ink">授权与审计尚未接入。用户对话、题目正文、模型输入输出和工具参数保持关闭，当前追踪摘要不授予正文查看权限。</p>
      <p className="mt-2 text-sm text-ink-2">后续接入须核对管理员权限、单条目标、到期状态和审计写入结果。此说明不是审计记录；本轮不提供正文或真实 Phoenix 跳转。</p>
      <button type="button" className={`${opsPrimaryClass} mt-3`} onClick={onOpen} disabled={busy}>
        {busy ? '正在检查…' : demo ? '演示正文访问检查' : '检查正文访问条件'}
      </button>
    </details>
  </OpsCard>
}

function RelatedAlerts({ client, runId, onOpenAlerts }: {
  client: OpsClient; runId: string; onOpenAlerts: (query: OpsQuery) => void
}) {
  const windowQuery = useRef<OpsQuery | null>(null)
  const load = useCallback((signal: AbortSignal) => {
    const now = Date.now()
    const query = {
      run_id: runId, from: new Date(now - 14 * 86_400_000).toISOString(),
      to: new Date(now).toISOString(), limit: 20,
    }
    windowQuery.current = query
    return client.listAlerts(query, signal)
  }, [client, runId])
  const result = useOpsQuery<OpsPage<OpsAlert>>(load)
  const openAll = () => {
    const query = windowQuery.current
    onOpenAlerts(query ? { run_id: runId, from: query.from, to: query.to } : { run_id: runId })
  }
  return <OpsCard title="关联异常轮次" action={<button type="button" className={opsButtonClass} onClick={openAll}>在异常中心查看</button>}>
    <p className="mb-3 text-xs text-ink-2">按 run_id 查询完整轮次关联；展示最近 14 天内首次发现的轮次，首屏最多 20 条。更早仍活动的轮次可能不在此窗口内。</p>
    <OpsFeedback loading={result.loading} error={result.error} hasData={!!result.data}
      retryLabel="重新加载关联异常"
      empty={result.data?.items.length === 0} emptyText="此窗口内无关联轮次；不代表本次运行成功或没有质量问题。" onRetry={result.refresh} />
    <OpsMetaNotice meta={result.data} lastSuccess={result.lastSuccess} />
    <ul className="mt-3 space-y-2">{result.data?.items.map(alert => <li key={alert.alert_id} className="rounded-lg border border-line bg-page p-3">
      <button type="button" className={`${opsButtonClass} w-full flex-wrap justify-start gap-2 text-left`}
        onClick={() => onOpenAlerts({ alert_id: alert.alert_id })}>
        <span>{opsAlertRuleLabel(alert.rule_id)} · 第 {alert.episode_no} 轮</span>
        <OpsBadge value={alert.status} /><OpsBadge value={alert.condition_state} />
        <span className="w-full break-all text-xs text-ink-2">{alert.alert_id}</span>
      </button>
      <p className="mt-2 text-xs text-ink-2">首次发现 {opsTime(alert.first_seen_at)} · 影响运行 {opsNumber(alert.affected_run_count)}</p>
      {alert.condition_state === 'unknown' && <p className="mt-1 text-sm text-ink-2">条件未知，不能宣布恢复。</p>}
      {alert.rule_id === 'run_failure' && <p className="mt-1 text-sm text-ink-2">离散失败事件，轮次关闭不代表业务成功。</p>}
    </li>)}</ul>
    {result.data?.page.has_more && <button type="button" className={`${opsPrimaryClass} mt-3`} onClick={openAll}>前往异常中心加载更多</button>}
  </OpsCard>
}
