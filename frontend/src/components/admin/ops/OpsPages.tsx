import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type {
  OpsAlert, OpsClient, OpsDependency, OpsOverview, OpsPage, OpsQuery, OpsRate, OpsRun,
} from '../../../types/ops'
import {
  OpsBadge, OpsCard, OpsFacts, OpsFeedback, OpsFilters, OpsMetaNotice, OpsReasons,
  OpsRunStates, opsButtonClass, opsDuration, opsInputClass, opsLabel, opsNumber,
  opsPercent, opsPrimaryClass, opsTime,
} from './OpsShared'
import type { OpsFilterField } from './OpsShared'
import { useOpsQuery } from './useOpsQuery'

const overviewFields: OpsFilterField[] = [
  { name: 'owner_user_id', label: '归属账号 ID' },
  { name: 'entrypoint', label: '出题入口', options: ['parameterized', 'conversation'] },
]
const runFields: OpsFilterField[] = [
  ...overviewFields,
  { name: 'execution_status', label: '执行状态', options: ['accepted', 'running', 'completed', 'failed', 'cancelled', 'unknown'] },
  { name: 'quality_status', label: '交付质量', options: ['met', 'attention', 'not_evaluated', 'unknown'] },
  { name: 'observation_flag', label: '观察标记', options: ['waiting_suspected', 'long_running_suspected', 'heartbeat_stale'] },
  { name: 'session_id', label: '会话 ID' },
  { name: 'batch_id', label: '批次 ID' },
  { name: 'trace_id', label: 'SDK / Phoenix Trace ID' },
]
const dependencyFields: OpsFilterField[] = [
  { name: 'scope', label: '范围（默认平台）', options: ['platform', 'account'] },
  { name: 'owner_user_id', label: '账号 ID（账号范围必填）' },
  { name: 'kind', label: '依赖类型', options: ['model', 'embedding', 'reranker', 'redis', 'vector_store', 'database', 'phoenix'] },
  { name: 'status', label: '依赖状态', options: ['healthy', 'degraded', 'unavailable', 'unknown'] },
]
const alertFields: OpsFilterField[] = [
  { name: 'alert_id', label: '告警 ID（通知精确定位）' },
  { name: 'status', label: '轮次状态', options: ['firing', 'resolved'] },
  { name: 'rule_id', label: '规则', options: ['dependency_failure', 'waiting_suspected', 'long_running_suspected', 'heartbeat_stale', 'run_failure', 'quality_attention'] },
  { name: 'severity', label: '级别', options: ['warning', 'critical'] },
  { name: 'scope', label: '范围', options: ['platform', 'account', 'run'] },
  { name: 'owner_user_id', label: '归属账号 ID' },
  { name: 'run_id', label: '关联运行 ID（完整轮次关联）' },
]

interface CursorState<T> {
  data: OpsPage<T> | null
  loading: boolean
  error: string
  appended: boolean
  lastSuccess: string | null
}

/** 首屏定时刷新；追加后冻结集合，刷新重新获取第一页。 */
function useCursorPage<T>(
  load: (query: OpsQuery, signal: AbortSignal) => Promise<OpsPage<T>>,
  query: OpsQuery,
  identify: (item: T) => string,
) {
  const [state, setState] = useState<CursorState<T>>({
    data: null, loading: true, error: '', appended: false, lastSuccess: null,
  })
  const current = useRef<OpsPage<T> | null>(null)
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const busy = useRef(false)
  const paused = useRef(false)
  const anchoredQuery = useRef<OpsQuery>(query)

  const request = useCallback(async (append: boolean, reset = false) => {
    if (append && (busy.current || !current.current?.page.has_more)) return
    controller.current?.abort()
    const serial = ++generation.current
    const abort = new AbortController()
    controller.current = abort
    busy.current = true
    paused.current = append
    if (reset) current.current = null
    setState(previous => ({
      ...previous, data: reset ? null : previous.data, loading: true, error: '',
      appended: append, lastSuccess: reset ? null : previous.lastSuccess,
    }))
    const nextQuery: OpsQuery = append
      ? { ...anchoredQuery.current, limit: 20, cursor: current.current?.page.next_cursor ?? undefined }
      : { ...query, limit: 20 }
    try {
      const next = await load(nextQuery, abort.signal)
      if (abort.signal.aborted || serial !== generation.current) return
      if (!append) {
        anchoredQuery.current = { ...query }
        if (next.window) {
          anchoredQuery.current.from = next.window.from
          anchoredQuery.current.to = next.window.to
        }
      }
      const previous = append ? current.current : null
      const items = new Map<string, T>()
      for (const item of previous?.items ?? []) items.set(identify(item), item)
      for (const item of next.items) items.set(identify(item), item)
      const warnings = new Map<string, OpsPage<T>['warnings'][number]>()
      for (const warning of [...(previous?.warnings ?? []), ...next.warnings]) {
        warnings.set(`${warning.code}:${warning.message}`, warning)
      }
      const data: OpsPage<T> = {
        ...next, items: [...items.values()], warnings: [...warnings.values()],
        data_state: previous?.data_state === 'partial' ? 'partial' : next.data_state,
        window: previous?.window ?? next.window,
      }
      current.current = data
      setState({ data, loading: false, error: '', appended: append, lastSuccess: new Date().toISOString() })
    } catch (error: unknown) {
      if (!abort.signal.aborted && serial === generation.current) {
        setState(previous => ({ ...previous, loading: false,
          error: error instanceof Error ? error.message : '运维摘要暂不可用，请重新加载第一页' }))
      }
    } finally {
      if (serial === generation.current) busy.current = false
    }
  }, [identify, load, query])

  useEffect(() => {
    void request(false, true)
    const tick = () => {
      if (!document.hidden && !busy.current && !paused.current) void request(false)
    }
    const timer = window.setInterval(tick, 15_000)
    document.addEventListener('visibilitychange', tick)
    return () => {
      generation.current += 1
      controller.current?.abort()
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [request])

  const refresh = useCallback(() => { void request(false) }, [request])
  const loadMore = useCallback(() => { void request(true) }, [request])
  return { ...state, refresh, loadMore }
}

const runIdentity = (run: OpsRun) => run.run_id
const dependencyIdentity = (dependency: OpsDependency) => JSON.stringify([dependency.dependency_id, dependency.scope_id])
const alertIdentity = (alert: OpsAlert) => alert.alert_id

function PanelHeading({ title, description, children }: {
  title: string; description: string; children?: ReactNode
}) {
  return <div className="flex flex-wrap items-start justify-between gap-3">
    <div><h2 className="text-xl font-semibold text-ink">{title}</h2>
      <p className="mt-1 max-w-4xl text-sm text-ink-2">{description}</p></div>
    {children}
  </div>
}

function PageFooter<T>({ page, count, loading, appended, refresh, loadMore }: {
  page: OpsPage<T> | null; count: number; loading: boolean; appended: boolean;
  refresh: () => void; loadMore: () => void
}) {
  return <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-white p-4">
    <div className="text-sm text-ink-2">
      <p>已加载 {count} 条 · 每页 20 条 · 不提供不可靠的总数</p>
      <p>{appended ? '已追加分页，自动刷新暂停；刷新将回到第一页。' : '首屏每 15 秒自动刷新；页面隐藏时暂停。'}</p>
      {page && <p>集合基准 as_of：{opsTime(page.page.as_of)}；状态可能继续变化。</p>}
    </div>
    <div className="flex flex-wrap gap-2">
      <button type="button" className={opsButtonClass} disabled={loading} onClick={refresh}>刷新第一页</button>
      {page?.page.has_more && <button type="button" className={opsPrimaryClass}
        disabled={loading || !page.page.next_cursor} onClick={loadMore}>加载更多</button>}
      {page && !page.page.has_more && <span className="self-center text-sm text-ink-2">已到最后一页</span>}
    </div>
  </div>
}

function RateCard({ title, rate, explanation }: { title: string; rate: OpsRate; explanation: string }) {
  return <div className="rounded-xl border border-line bg-white p-4">
    <h4 className="text-sm font-medium text-ink">{title}</h4>
    <p className="mt-2 text-2xl font-semibold text-primary">{opsPercent(rate.value)}</p>
    <p className="mt-2 text-sm text-ink-2">分子 {opsNumber(rate.numerator)} / 分母 {opsNumber(rate.denominator)}</p>
    <p className="text-sm text-ink-2">排除未知：{opsNumber(rate.excluded_unknown)}</p>
    {rate.reason && <p className="mt-1 text-sm text-ink">{opsLabel(rate.reason)}</p>}
    <p className="mt-2 text-xs leading-relaxed text-ink-2">{explanation}</p>
  </div>
}

export function OpsOverviewPanel({ client, onOpenRuns, onOpenAlerts }: {
  client: OpsClient; onOpenRuns: (query?: OpsQuery) => void; onOpenAlerts: (query?: OpsQuery) => void
}) {
  const [query, setQuery] = useState<OpsQuery>({})
  const load = useCallback((signal: AbortSignal) => client.getOverview(query, signal), [client, query])
  const result = useOpsQuery<OpsOverview>(load)
  const { data } = result
  const cohort: OpsQuery = data ? { ...query, from: data.window.from, to: data.window.to } : query
  return <div className="space-y-4">
    <PanelHeading title="出题运维概览" description="统计范围：SDK Agent v1 已观测运行；执行正常结束、交付质量与详细追踪分别判定。">
      <button type="button" className={opsButtonClass} disabled={result.loading} onClick={result.refresh}>刷新概览</button>
    </PanelHeading>
    <OpsFilters fields={overviewFields} query={query} onApply={setQuery} />
    <OpsFeedback loading={result.loading} error={result.error} hasData={!!data} onRetry={result.refresh} />
    <OpsMetaNotice meta={data} lastSuccess={result.lastSuccess} />
    {data && <>
      <OpsCard title="采集窗口与覆盖范围" action={<OpsBadge value={data.collection.coverage_state} />}>
        <OpsFacts items={[
          ['受理时间窗口 [from, to)', `${opsTime(data.window.from)} — ${opsTime(data.window.to)}`],
          ['采集开始', opsTime(data.collection.started_at)],
          ['已观测运行', opsNumber(data.collection.observed_runs)],
          ['部分采集运行', opsNumber(data.collection.partial_runs)],
          ['排除的历史未采集记录', opsNumber(data.collection.excluded_legacy_records)],
          ['执行状态未知运行', opsNumber(data.collection.unknown_status_runs)],
        ]} />
        <p className="mt-3 text-xs text-ink-2">按 accepted_at 归入窗口；历史批次不补造 run。未知和未采集样本不补零，不反推未记录失败数。</p>
      </OpsCard>
      <OpsCard title="当前运行与活动异常（不受历史时间窗限制）">
        <p className="mb-3 text-sm text-ink-2">时点：{opsTime(data.current.as_of)}，包含超期但仍活动的保护摘要。</p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <CurrentMetric label="已受理未开始" value={data.current.accepted_count} />
          <CurrentMetric label="运行中" value={data.current.running_count} />
          <div className="rounded-lg bg-page p-4"><p className="text-sm text-ink-2">疑似异常运行</p>
            <p className="mt-2 text-2xl font-semibold text-ink">{opsNumber(data.current.suspected_count)}</p>
            <p className="mt-1 text-xs text-ink-2">观察标记不改变执行终态</p></div>
          <CurrentMetric label="活动告警轮次" value={data.current.active_alert_count} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className={opsButtonClass}
            onClick={() => onOpenRuns({ owner_user_id: query.owner_user_id, entrypoint: query.entrypoint, execution_status: 'running' })}>查看近 24 小时受理的运行中记录</button>
          <button type="button" className={opsButtonClass}
            onClick={() => onOpenAlerts({ owner_user_id: query.owner_user_id, status: 'firing' })}>查看近 24 小时新建的活动告警</button>
        </div>
        <p className="mt-3 text-xs text-ink-2">已受理数不是持久队列深度。以上明细仅覆盖近 24 小时，不能覆盖全部当前记录，尤其是超 14 天仍受活动保护的摘要；告警明细不支持入口筛选。</p>
      </OpsCard>
      <OpsCard title="窗口内执行状态" action={<button type="button" className={opsButtonClass} onClick={() => onOpenRuns(cohort)}>查看出题运行</button>}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
          {Object.entries(data.execution.counts).map(([status, count]) => <button key={status} type="button"
            className="min-h-11 rounded-lg bg-page p-3 text-left transition-colors hover:bg-primary-light focus-visible:outline-2 focus-visible:outline-primary"
            onClick={() => onOpenRuns({ ...cohort, execution_status: status })}>
            <p className="text-sm text-ink-2">{opsLabel(status)}</p>
            <p className="mt-1 text-xl font-semibold text-ink">{opsNumber(count)}</p>
          </button>)}
        </div>
      </OpsCard>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <RateCard title="正常结束率" rate={data.execution.completion_rate}
          explanation="completed / (completed + failed)。已取消、已受理、运行中、未知均不进入分母；正常结束不保证交付质量。" />
        <RateCard title="交付需关注率" rate={data.quality_metrics.attention_rate}
          explanation="已正常结束且质量已判定的运行中，attention / (met + attention)；同一运行多种原因只计一次。" />
        <RateCard title="最终题量不足率" rate={data.quality_metrics.shortfall_rate}
          explanation="已正常结束、题量状态已知的运行中，最终可交付题量不足的比例。" />
        <RateCard title="审核跳过率" rate={data.quality_metrics.review_skip_rate}
          explanation="已正常结束、应审数量大于零且跳过数已知的运行中，存在跳审的运行比例。" />
        <RateCard title="降级率" rate={data.quality_metrics.degraded_rate}
          explanation="已正常结束且降级事实已知的运行中，存在明确降级事件的比例。" />
        <RateCard title="最终版本审核覆盖率" rate={data.quality_metrics.review_coverage_rate}
          explanation="已正常结束且最终审核计数完整的运行中，Σ已明确审核题数 / Σ应审题数；未知放行不计覆盖。" />
      </div>
      <OpsCard title="重出尝试与覆盖">
        <div className="grid gap-4 md:grid-cols-2">
          <RateCard title="有重出尝试的运行比例" rate={data.regeneration_metrics.run_rate}
            explanation="已正常结束且尝试数已知的运行中，有实际启动重出尝试的运行比例；不是尝试数 / 目标题数。" />
          <OpsFacts items={[
            ['逻辑重出尝试总数', opsNumber(data.regeneration_metrics.attempt_total)],
            ['有效样本运行数', opsNumber(data.regeneration_metrics.sample_runs)],
            ['已结束重出尝试耗时之和', opsDuration(data.regeneration_metrics.total_attempt_ms)],
            ['频繁重出告警阈值', '未配置（unconfigured）'],
          ]} />
        </div>
        <p className="mt-3 text-xs text-ink-2">重出可并行，耗时之和不是运行墙钟耗时；成功的重出题目可能被后续去重丢弃。</p>
      </OpsCard>
      <OpsCard title="保留与清理" action={<OpsBadge value={data.retention.last_cleanup_status} />}>
        <OpsFacts items={[
          ['详细追踪保留', `${opsNumber(data.retention.trace_days)} 天`],
          ['运行等摘要保留', `${opsNumber(data.retention.summary_days)} 天`],
          ['清理周期', `${opsNumber(data.retention.cleanup_interval_hours)} 小时`],
          ['最近清理', opsTime(data.retention.last_cleanup_at)],
        ]} />
        {data.retention.last_cleanup_status === 'failed' && <p role="alert" className="mt-3 text-sm text-red-700">最近清理失败；不能视为历史数据已删除，请检查概览警告。</p>}
        <p className="mt-3 text-xs text-ink-2">正文到期即关闭入口；物理清理按周期执行。活动运行、活动故障与待检测状态仅延后清理必要摘要，不延长正文保留。</p>
      </OpsCard>
    </>}
  </div>
}

function CurrentMetric({ label, value }: { label: string; value: number | null }) {
  return <div className="rounded-lg border border-line bg-page p-4">
    <p className="text-sm text-ink-2">{label}</p>
    <p className="mt-2 text-2xl font-semibold text-primary">{opsNumber(value)}</p>
  </div>
}

interface RunsProps {
  client: OpsClient
  initialQuery?: OpsQuery
  onOpenRun: (id: string) => void
}

export function RunsPanel(props: RunsProps) {
  return <RunsContent key={JSON.stringify(props.initialQuery ?? {})} {...props} />
}

function RunsContent({ client, initialQuery, onOpenRun }: RunsProps) {
  const [query, setQuery] = useState<OpsQuery>(initialQuery ?? {})
  const load = useCallback((next: OpsQuery, signal: AbortSignal) => client.listRuns(next, signal), [client])
  const result = useCursorPage(load, query, runIdentity)
  return <div className="space-y-4">
    <PanelHeading title="出题运行" description="按受理时间筛选；仅展示已采集的 SDK Agent 运行。疑似观察不改变业务状态，执行、交付质量和追踪独立展示。" />
    <OpsFilters fields={runFields} query={query} onApply={setQuery} />
    <OpsMetaNotice meta={result.data} lastSuccess={result.lastSuccess} />
    <OpsFeedback {...result} hasData={!!result.data} empty={result.data?.items.length === 0} onRetry={result.refresh} />
    {result.data?.window && <p className="text-sm text-ink-2">
      受理窗口：{opsTime(result.data.window.from)} — {opsTime(result.data.window.to)}（左闭右开）
    </p>}
    <div className="space-y-3">{result.data?.items.map(run => <OpsCard key={run.run_id} title={run.run_id}
      action={<button type="button" className={opsPrimaryClass} onClick={() => onOpenRun(run.run_id)} aria-label={`查看运行 ${run.run_id}`}>查看详情</button>}>
      <OpsRunStates run={run} />
      <div className="mt-4"><OpsFacts items={[
        ['账号 / 入口', `${run.owner_user_id} / ${opsLabel(run.entrypoint)}`],
        ['受理时间', opsTime(run.accepted_at)],
        ['受理至开始等待', opsDuration(run.wait_ms)],
        [run.execution_status === 'running' ? '运行至今（非最终耗时）' : '最终运行耗时',
          opsDuration(run.execution_status === 'running' ? run.running_age_ms : run.elapsed_ms)],
        ['当前阶段', opsLabel(run.current_stage)],
        ['最终实际数 / 目标题量', `${opsNumber(run.counts.actual_count)} / ${opsNumber(run.counts.target_count)}`],
        ['审核覆盖', opsPercent(run.review.coverage_rate)],
        ['逻辑重出尝试', opsNumber(run.regeneration.attempt_count)],
        ['采集 / 版本', `${opsLabel(run.collection_state)} / ${run.revision}`],
        ['摘要更新', opsTime(run.updated_at)],
      ]} /></div>
      <div className="mt-3 space-y-2">
        <div><p className="mb-1 text-sm text-ink-2">质量原因</p><OpsReasons codes={run.quality.reason_codes} /></div>
        <div><p className="mb-1 text-sm text-ink-2">疑似异常观察</p><OpsReasons codes={run.observation_flags} /></div>
        {run.observation_unknown_reason && <p className="text-sm text-ink-2">观察未知：{opsLabel(run.observation_unknown_reason)}（{run.observation_unknown_reason}）</p>}
      </div>
    </OpsCard>)}</div>
    <PageFooter {...result} page={result.data} count={result.data?.items.length ?? 0} />
  </div>
}

export function DependenciesPanel({ client, onOpenRuns }: {
  client: OpsClient; onOpenRuns: (query?: OpsQuery) => void
}) {
  const [query, setQuery] = useState<OpsQuery>({})
  const [source, setSource] = useState('')
  const load = useCallback((next: OpsQuery, signal: AbortSignal) => client.listDependencies(next, signal), [client])
  const result = useCursorPage(load, query, dependencyIdentity)
  const visible = result.data?.items.filter(item => !source || item.source === source) ?? []
  return <div className="space-y-4">
    <PanelHeading title="依赖状态" description="当前快照，不接收历史时间窗口；查询不会主动调用模型。个人凭据故障按账号隔离，不能据此推断平台共享服务故障。" />
    <OpsFilters fields={dependencyFields} query={query} timeWindow={false} onApply={next => { setQuery(next); setSource('') }} />
    <label className="block max-w-sm space-y-1 text-sm text-ink"><span>证据来源（筛选已加载记录）</span>
      <select className={opsInputClass} value={source} onChange={event => setSource(event.target.value)}>
        <option value="">全部来源</option>
        {['passive', 'probe', 'mixed', 'none'].map(value => <option key={value} value={value}>{opsLabel(value)}</option>)}
      </select>
    </label>
    <OpsMetaNotice meta={result.data} lastSuccess={result.lastSuccess} />
    <p className="text-sm text-ink-2">样本有效期：{opsNumber(result.data?.observation_window_seconds)} 秒；保留记录不等于当前观测新鲜。Phoenix 健康不证明单条 trace 可读。</p>
    <OpsFeedback {...result} hasData={!!result.data} empty={!!result.data && visible.length === 0}
      emptyText={source ? '已加载记录中没有此来源；可加载更多或清除来源筛选。' : undefined} onRetry={result.refresh} />
    <div className="grid gap-3 xl:grid-cols-2">{visible.map(dependency => <DependencyCard key={dependencyIdentity(dependency)}
      dependency={dependency} generatedAt={result.data?.generated_at ?? ''} onOpenRuns={onOpenRuns} />)}</div>
    <PageFooter {...result} page={result.data} count={result.data?.items.length ?? 0} />
  </div>
}

function DependencyCard({ dependency, generatedAt, onOpenRuns }: {
  dependency: OpsDependency; generatedAt: string; onOpenRuns: (query?: OpsQuery) => void
}) {
  const fresh = dependency.fresh_until != null && dependency.checked_at != null
    && new Date(dependency.fresh_until).getTime() > new Date(generatedAt).getTime()
  const status = fresh ? dependency.status : 'unknown'
  return <OpsCard title={`${opsLabel(dependency.kind)} · ${dependency.dependency_id}`} action={<OpsBadge value={status} />}>
    <OpsFacts items={[
      ['范围 / 账号', `${opsLabel(dependency.scope)} / ${dependency.owner_user_id ?? '平台共享'}`],
      ['范围标识', dependency.scope_id],
      ['凭据范围', opsLabel(dependency.credential_scope)],
      ['证据来源', opsLabel(dependency.source)],
      ['最近观测', opsTime(dependency.checked_at)],
      ['新鲜度有效至', opsTime(dependency.fresh_until)],
      ['新鲜度', dependency.checked_at == null ? '从未观察／未知' : fresh ? '响应生成时有效' : '观测已过期／未知'],
      ['采集状态', opsLabel(dependency.collection_state)],
      ['最近成功', opsTime(dependency.last_success_at)],
      ['最近失败', opsTime(dependency.last_failure_at)],
      ['连续失败 / 连续成功', `${opsNumber(dependency.consecutive_failures)} / ${opsNumber(dependency.consecutive_successes)}`],
      ['当前 5 分钟影响运行数（去重）', opsNumber(dependency.affected_run_count)],
    ]} />
    {dependency.error_code && <p className="mt-3 text-sm text-ink">{opsLabel(dependency.error_code)}（{dependency.error_code}）</p>}
    {dependency.owner_user_id && <button type="button" className={`${opsButtonClass} mt-3`}
      onClick={() => onOpenRuns({ owner_user_id: dependency.owner_user_id ?? undefined })}>查看该账号运行</button>}
    <p className="mt-3 text-xs text-ink-2">状态基于响应生成时的证据；连续失败与恢复按独立观测累计，不按页面刷新次数累计。</p>
  </OpsCard>
}

interface AlertsProps {
  client: OpsClient
  initialQuery?: OpsQuery
  onOpenRun: (id: string) => void
}

export function AlertsPanel(props: AlertsProps) {
  return <AlertsContent key={JSON.stringify(props.initialQuery ?? {})} {...props} />
}

function AlertsContent({ client, initialQuery, onOpenRun }: AlertsProps) {
  const [query, setQuery] = useState<OpsQuery>(initialQuery ?? {})
  const load = useCallback((next: OpsQuery, signal: AbortSignal) => client.listAlerts(next, signal), [client])
  const result = useCursorPage(load, query, alertIdentity)
  const exact = !!query.alert_id && !query.from && !query.to
  return <div className="space-y-4">
    <PanelHeading title="异常中心" description="按轮次首次发现时间筛选。通知已读不等于故障恢复；轮次状态与最近条件评估分别展示。" />
    <OpsFilters fields={alertFields} query={query} onApply={setQuery} />
    {exact && <p className="rounded-lg bg-primary-light p-3 text-sm text-ink">正按告警 ID 定位整个保留期，未附带默认近 24 小时窗口。</p>}
    <OpsMetaNotice meta={result.data} lastSuccess={result.lastSuccess} />
    <OpsFeedback {...result} hasData={!!result.data} empty={result.data?.items.length === 0}
      emptyText={exact ? '未找到该轮次，记录可能已过保留期；不存在的告警 ID 也返回空结果。' : undefined} onRetry={result.refresh} />
    {result.data?.window && <p className="text-sm text-ink-2">
      轮次首次发现窗口：{opsTime(result.data.window.from)} — {opsTime(result.data.window.to)}（左闭右开）
    </p>}
    <div className="space-y-3">{result.data?.items.map(alert => <AlertCard key={alert.alert_id} alert={alert} onOpenRun={onOpenRun} />)}</div>
    <PageFooter {...result} page={result.data} count={result.data?.items.length ?? 0} />
  </div>
}

function AlertCard({ alert, onOpenRun }: { alert: OpsAlert; onOpenRun: (id: string) => void }) {
  const evidence = alert.evidence
  return <article className="min-w-0 rounded-xl border border-line bg-white p-4 shadow-sm sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="font-semibold text-ink">{opsLabel(alert.rule_id)} · 第 {alert.episode_no} 轮</h3>
        <p className="mt-1 break-all text-xs text-ink-2">{alert.alert_id}</p></div>
      <div className="flex flex-wrap gap-2"><OpsBadge value={alert.severity} /><OpsBadge value={alert.status} /><OpsBadge value={alert.condition_state} /></div>
    </div>
    <div className="mt-4"><OpsFacts items={[
      ['范围 / 归属', `${opsLabel(alert.scope)} / ${alert.owner_user_id ?? alert.scope_id}`],
      ['影响运行数（去重）', opsNumber(alert.affected_run_count)],
      ['首次发现', opsTime(alert.first_seen_at)],
      ['最近异常证据', opsTime(alert.last_seen_at)],
      ['最近条件评估', opsTime(alert.last_evaluated_at)],
      ['去重异常证据数', opsNumber(alert.occurrence_count)],
    ]} /></div>
    {alert.condition_state === 'unknown' && <p role="status" className="mt-3 rounded-lg bg-star/5 p-3 text-sm text-ink">
      最近条件未知，可能缺少有效样本或采集证据；不能据此宣布故障恢复。
    </p>}
    {alert.rule_id === 'run_failure' && <p className="mt-3 rounded-lg bg-page p-3 text-sm text-ink">
      离散运行失败事件：通知后轮次即关闭；关闭不代表本次业务成功，也不会发送“已成功”恢复通知。
    </p>}
    <details className="mt-4 rounded-lg border border-line p-3">
      <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium text-primary transition-colors focus-visible:outline-2 focus-visible:outline-primary">轮次证据、恢复与通知</summary>
      <div className="mt-4 space-y-4">
        <OpsFacts items={[
          ['轮次关联键', alert.dedupe_key], ['对象标识', alert.subject_id],
          ['关闭时间', opsTime(alert.resolved_at)],
          ['最近迁移原因', alert.last_transition_reason ? `${opsLabel(alert.last_transition_reason)}（${alert.last_transition_reason}）` : '未知／尚未产生'],
          ['指标', evidence.metric ?? '未知'],
          ['观测值 / 阈值', `${opsNumber(evidence.value)} / ${opsNumber(evidence.threshold)}`],
          ['分子 / 分母', `${opsNumber(evidence.numerator)} / ${opsNumber(evidence.denominator)}`],
          ['有效样本', opsNumber(evidence.sample_count)],
          ['证据窗口开始', opsTime(evidence.window_from)], ['证据窗口结束', opsTime(evidence.window_to)],
          ['证据原因', evidence.reason_code ? `${opsLabel(evidence.reason_code)}（${evidence.reason_code}）` : '未知／不适用'],
          ['最近通知', opsTime(alert.notification.last_sent_at)],
          ['通知类别', opsLabel(alert.notification.last_kind)],
          ['下次可提醒时间', opsTime(alert.notification.next_eligible_at)],
        ]} />
        {evidence.reason_counts == null ? <p className="text-sm text-ink-2">质量原因桶未知／不适用。</p>
          : <OpsFacts items={Object.entries(evidence.reason_counts).map(([reason, count]) => [opsLabel(reason), opsNumber(count)])} />}
        {alert.rule_id === 'quality_attention' && <p className="text-xs text-ink-2">
          质量告警按最近 5 分钟 finished_at 取已正常结束且质量已判定的样本；与概览 accepted_at 窗口不同。
          同一运行可命中多个原因桶，桶之和不等于异常总数；低样本条件为未知。
        </p>}
        <p className="text-xs text-ink-2">持续提醒需要新异常证据及冷却间隔，不按轮询次数增加发生次数。样本运行不是完整影响列表。</p>
      </div>
    </details>
    <div className="mt-3 flex flex-wrap gap-2">
      {alert.sample_run_ids.map(runId => <button key={runId} type="button" className={opsButtonClass}
        onClick={() => onOpenRun(runId)}>样本运行：<span className="ml-1 break-all">{runId}</span></button>)}
      {alert.sample_run_ids.length === 0 && <p className="text-sm text-ink-2">无样本运行；不据此推断影响数为零。</p>}
      {alert.scope === 'run' && !alert.sample_run_ids.includes(alert.scope_id) && <button type="button"
        className={opsButtonClass} onClick={() => onOpenRun(alert.scope_id)}>查看关联运行</button>}
    </div>
  </article>
}
