/** 仅供 DEV 动态导入：独立、可取消、无网络和持久化副作用的合成数据源。 */
import type {
  OpsAlert, OpsClient, OpsDependency, OpsEffectiveConfig, OpsExecutionStatus, OpsMeta,
  OpsMonitoringMetric, OpsNotification, OpsOverview, OpsPage, OpsQuery, OpsRate,
  OpsReviewVersions, OpsRun, OpsRunDetail, OpsSelfMonitoring, OpsStage, OpsTraceAccessResult, OpsWindow,
} from '../types/ops'
import { ApiError } from './session'

export type DemoScenario = 'normal' | 'loading' | 'empty' | 'partial' | 'error'
  | 'trace_denied' | 'trace_audit_failed' | 'trace_expired' | 'trace_simulated_success'

const SECOND = 1000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
const CURSOR_LIFETIME = 15 * MINUTE
const EXECUTION_STATUSES: OpsExecutionStatus[] = ['accepted', 'running', 'completed', 'failed', 'cancelled', 'unknown']
type Endpoint = 'overview' | 'runs' | 'dependencies' | 'alerts'

interface Cursor {
  endpoint: Endpoint
  signature: string
  asOf: string
  window?: OpsWindow
  anchor: [string, string]
  createdAt: number
}

interface Selection {
  asOf: string
  window?: OpsWindow
  limit: number
  signature: string
  cursor?: Cursor
}

const iso = (milliseconds: number): string => new Date(milliseconds).toISOString()

function invalidQuery(): never {
  throw new ApiError('查询参数无效，请检查筛选条件', 'VALIDATION_ERROR', 422)
}

function exact(query: OpsQuery, key: string, actual: string | null): boolean {
  return query[key] === undefined || query[key] === actual
}

function querySignature(query: OpsQuery, window: OpsWindow | undefined, limit: number): string {
  const entries = Object.entries(query)
    .filter(([key, value]) => !['cursor', 'from', 'to', 'limit'].includes(key) && value !== undefined)
    .map(([key, value]) => [key, String(value)])
  entries.push(['limit', String(limit)])
  if (window) entries.push(['from', window.from], ['to', window.to])
  return JSON.stringify(entries.sort(([left], [right]) => left.localeCompare(right)))
}

function checkEnum(query: OpsQuery, key: string, allowed: readonly string[]): void {
  const value = query[key]
  if (value !== undefined && (typeof value !== 'string' || !allowed.includes(value))) invalidQuery()
}

function checkQuery(endpoint: Endpoint, query: OpsQuery): void {
  const pagination = ['limit', 'cursor']
  const cohort = ['from', 'to', 'owner_user_id', 'entrypoint']
  const keys: Record<Endpoint, string[]> = {
    overview: cohort,
    runs: [...cohort, ...pagination, 'execution_status', 'quality_status', 'observation_flag', 'session_id', 'batch_id', 'trace_id'],
    dependencies: [...pagination, 'scope', 'owner_user_id', 'kind', 'status'],
    alerts: [...pagination, 'from', 'to', 'alert_id', 'status', 'rule_id', 'severity', 'scope', 'owner_user_id', 'run_id'],
  }
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue
    if (!keys[endpoint].includes(key)) invalidQuery()
    if (key === 'limit') {
      if (!/^\d+$/.test(String(value)) || !Number.isInteger(Number(value)) || Number(value) < 1 || Number(value) > 100) invalidQuery()
    } else if (typeof value !== 'string' || !value || value.length > 2048) invalidQuery()
  }
  checkEnum(query, 'entrypoint', ['parameterized', 'conversation'])
  if (endpoint === 'runs') {
    checkEnum(query, 'execution_status', EXECUTION_STATUSES)
    checkEnum(query, 'quality_status', ['met', 'attention', 'not_evaluated', 'unknown'])
    checkEnum(query, 'observation_flag', ['waiting_suspected', 'long_running_suspected', 'heartbeat_stale'])
  }
  if (endpoint === 'dependencies') {
    checkEnum(query, 'scope', ['platform', 'account'])
    checkEnum(query, 'kind', ['model', 'embedding', 'reranker', 'redis', 'vector_store', 'database', 'phoenix'])
    checkEnum(query, 'status', ['healthy', 'degraded', 'unavailable', 'unknown'])
    if ((query.scope === 'account' && !query.owner_user_id)
      || (query.scope === 'platform' && query.owner_user_id !== undefined)) invalidQuery()
  }
  if (endpoint === 'alerts') {
    checkEnum(query, 'scope', ['platform', 'account', 'run'])
    checkEnum(query, 'status', ['firing', 'resolved'])
    checkEnum(query, 'severity', ['warning', 'critical'])
    if (query.rule_id !== undefined && (typeof query.rule_id !== 'string'
      || !/^[a-z][a-z0-9_]{0,99}$/.test(query.rule_id))) invalidQuery()
  }
}

function parseTime(value: string | number | undefined, fallback: number): number {
  if (value === undefined) return fallback
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$/.test(value)) return invalidQuery()
  const parsed = Date.parse(value)
  if (!Number.isFinite(parsed) || iso(parsed).slice(0, 19) !== value.slice(0, 19)) return invalidQuery()
  return parsed
}

function makeWindow(endpoint: Endpoint, query: OpsQuery, now: number): OpsWindow | undefined {
  if (endpoint === 'dependencies') return undefined
  if (endpoint === 'alerts' && query.alert_id !== undefined && query.from === undefined && query.to === undefined) return undefined
  const to = parseTime(query.to, now)
  const from = parseTime(query.from, to - DAY)
  if (from >= to || to > now || from > now || to - from > 14 * DAY) return invalidQuery()
  return { from: iso(from), to: iso(to), time_basis: endpoint === 'alerts' ? 'first_seen_at' : 'accepted_at' }
}

function inWindow(at: string, window?: OpsWindow): boolean {
  return window === undefined || (Date.parse(at) >= Date.parse(window.from) && Date.parse(at) < Date.parse(window.to))
}

function matchesOwner(run: OpsRun, query: OpsQuery): boolean {
  return exact(query, 'owner_user_id', run.owner_user_id) && exact(query, 'entrypoint', run.entrypoint)
}

function matchesRun(run: OpsRun, query: OpsQuery, window?: OpsWindow): boolean {
  return matchesOwner(run, query) && inWindow(run.accepted_at, window)
    && exact(query, 'execution_status', run.execution_status) && exact(query, 'quality_status', run.quality.status)
    && (query.observation_flag === undefined || run.observation_flags?.some(flag => flag === query.observation_flag) === true)
    && exact(query, 'session_id', run.session_id) && exact(query, 'batch_id', run.batch_id)
    && (query.trace_id === undefined || query.trace_id === run.trace.sdk_trace_id || query.trace_id === run.trace.phoenix_trace_id)
}

/** 有界延迟，取消时清理定时器和监听器，不触发后续内存修改。 */
async function delay(signal: AbortSignal, milliseconds: number): Promise<void> {
  signal.throwIfAborted()
  if (milliseconds === 0) return
  await new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer)
      signal.removeEventListener('abort', abort)
      reject(signal.reason ?? new DOMException('请求已取消', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort)
      resolve()
    }, milliseconds)
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) abort()
  })
  signal.throwIfAborted()
}

function makeRun(index: number, now: number): OpsRunDetail['run'] {
  const mode = index % 10
  const runId = `demo_run_${String(index + 1).padStart(3, '0')}`
  const entrypoint = index % 2 === 0 ? 'parameterized' : 'conversation'
  const owner = index % 3 === 0 ? 'demo_user_a' : 'demo_user_b'
  const accepted = mode === 6 ? now - 4 * DAY - index * MINUTE : now - (index + 1) * 15 * MINUTE
  const started = accepted + SECOND
  const finished = started + 14 * SECOND
  const active = mode === 3 || mode === 4
  const missing = mode === 5
  const failed = mode === 2
  const cancelled = mode === 9
  const attention = mode === 1 || mode === 8
  const completed = !active && !missing && !failed && !cancelled
  const actual = missing ? null : attention ? 3 : completed ? 5 : 0
  const skipped = mode === 1 ? 1 : 0
  const covered = actual === null ? null : actual - skipped
  const sessionId = entrypoint === 'conversation' ? `demo_session_${Math.floor(index / 4) + 1}` : null
  return {
    run_id: runId, owner_user_id: owner, entrypoint, session_id: sessionId,
    batch_id: completed ? `demo_batch_${index + 1}` : null, revision: completed ? 5 : active ? 3 : 1,
    collection_state: missing ? 'not_collected' : 'complete',
    unknown_fields: missing ? [
      'counts.actual_count', 'review.required', 'review.eligible_count', 'review.covered_count',
      'review.passed_count', 'review.skipped_count', 'review.unknown_count', 'degradation.occurred',
      'degradation.reason_codes', 'quality.reason_codes', 'regeneration.attempt_count',
      'regeneration.succeeded_count', 'regeneration.failed_count', 'regeneration.in_flight_count',
      'regeneration.total_attempt_ms', 'started_at', 'observation_flags',
    ] : [],
    execution_status: missing ? 'unknown' : mode === 4 ? 'accepted' : mode === 3 ? 'running'
      : failed ? 'failed' : cancelled ? 'cancelled' : 'completed',
    execution_reason_code: failed ? 'MODEL_CALL_FAILED' : cancelled ? 'USER_CANCELLED' : null,
    accepted_at: iso(accepted), started_at: mode === 4 || missing ? null : iso(started),
    finished_at: active || missing ? null : iso(finished),
    heartbeat_at: mode === 4 || missing ? null : iso(mode === 3 ? now - 3 * MINUTE : finished),
    updated_at: iso(active ? now - 5 * SECOND : missing ? accepted : finished),
    wait_ms: mode === 4 || missing ? null : SECOND,
    elapsed_ms: active || missing ? null : 14 * SECOND,
    running_age_ms: mode === 3 ? now - started : null,
    current_stage: mode === 4 ? 'queued' : missing ? 'unknown' : mode === 3 || failed ? 'generation' : 'finalizing',
    observation_flags: missing ? null : mode === 3 ? ['long_running_suspected', 'heartbeat_stale']
      : mode === 4 ? ['waiting_suspected'] : [],
    observation_checked_at: missing ? null : iso(now),
    observation_unknown_reason: missing ? 'NOT_COLLECTED' : null,
    counts: { target_count: 5, actual_count: actual, quantity_status: active || missing ? 'unknown' : actual !== null && actual >= 5 ? 'met' : 'shortfall' },
    review: {
      required: missing ? null : true, eligible_count: actual, covered_count: covered,
      passed_count: covered === null ? null : mode === 8 ? covered - 1 : covered,
      skipped_count: missing ? null : skipped, unknown_count: missing ? null : 0,
      coverage_rate: actual !== null && actual > 0 && covered !== null ? covered / actual : null,
      coverage_reason: missing ? 'not_collected' : actual === 0 ? 'empty_output' : null,
      status: missing || actual === 0 ? 'unknown' : skipped ? 'partial' : 'complete',
    },
    quality: {
      status: missing ? 'unknown' : active ? 'not_evaluated' : attention || failed || cancelled ? 'attention' : 'met',
      reason_codes: missing ? null : mode === 1 ? ['QUANTITY_SHORTFALL', 'REVIEW_SKIPPED', 'DEGRADED']
        : mode === 8 ? ['QUANTITY_SHORTFALL', 'REVIEW_FAILED', 'DEGRADED'] : failed || cancelled ? ['QUANTITY_SHORTFALL'] : [],
    },
    degradation: { occurred: missing ? null : attention, reason_codes: missing ? null : mode === 1 ? ['UNREVIEWED_RELEASE'] : mode === 8 ? ['MODEL_FALLBACK'] : [] },
    regeneration: {
      attempt_count: missing ? null : attention ? 2 : 0, succeeded_count: missing ? null : attention ? 1 : 0,
      failed_count: missing ? null : attention ? 1 : 0, in_flight_count: missing ? null : 0,
      total_attempt_ms: missing ? null : attention ? 1300 : 0,
    },
    trace: {
      sdk_trace_id: missing || mode === 4 ? null : `demo_sdk_trace_${index + 1}`,
      phoenix_trace_id: missing || mode === 4 || mode === 1 ? null : `demo_phoenix_trace_${index + 1}`,
      group_id: sessionId ?? runId,
      export_status: missing ? 'unknown' : mode === 4 ? 'not_started' : mode === 8 ? 'failed' : mode === 3 ? 'pending' : 'submitted',
      availability: missing ? 'not_collected' : mode === 6 ? 'expired' : mode === 7 ? 'forbidden'
        : mode === 8 ? 'unavailable' : mode === 3 || mode === 4 ? 'pending' : mode === 1 ? 'unknown' : 'available',
      complete: missing || active || attention || mode === 7 ? null : true,
      verified_at: missing || active || mode === 1 ? null : iso(now),
      reason_code: missing ? 'NOT_COLLECTED' : mode === 6 ? 'RETENTION_ELAPSED' : mode === 7 ? 'ACCESS_DENIED'
        : mode === 8 ? 'LOOKUP_UNAVAILABLE' : mode === 1 ? 'MAPPING_UNCONFIRMED' : active ? 'WAITING_FOR_EXPORT' : null,
      expires_at: missing || mode === 4 ? null : iso(started + 3 * DAY),
      viewer_path: !missing && !active && !attention && mode !== 6 && mode !== 7
        ? `/demo-ops/traces/${index + 1}` : null,
    },
  }
}

/** 阶段只记录已发生或明确跳过的事件，不用阶段耗时求和替代运行墙钟。 */
function makeStages(run: OpsRun): OpsStage[] | null {
  if (run.collection_state === 'not_collected') return null
  if (run.started_at === null) return []
  const start = Date.parse(run.started_at)
  const stages: OpsStage[] = []
  const names: OpsStage['name'][] = ['preparing', 'retrieval', 'generation', 'review', 'repair', 'persisting', 'finalizing']
  for (const [index, name] of names.entries()) {
    const stageId = `${run.run_id}_${name}`
    const atGeneration = name === 'generation'
    const running = atGeneration && run.execution_status === 'running'
    const failed = atGeneration && run.execution_status === 'failed'
    const skipped = name === 'repair' && run.regeneration.attempt_count === 0
    const stage: OpsStage = {
      stage_id: stageId, parent_stage_id: name === 'repair' ? `${run.run_id}_generation` : null,
      name, attempt_index: 1, status: skipped ? 'skipped' : running ? 'running' : failed ? 'failed' : 'completed',
      started_at: skipped ? null : iso(start + index * 2 * SECOND),
      finished_at: skipped || running ? null : iso(start + index * 2 * SECOND + (name === 'repair' ? 650 : 2 * SECOND)),
      elapsed_ms: skipped || running ? null : name === 'repair' ? 650 : 2 * SECOND,
      reason_code: skipped ? 'NOT_REQUIRED' : failed ? 'MODEL_CALL_FAILED' : null,
    }
    stages.push(stage)
    if (running || failed) break
    if (name === 'repair' && run.regeneration.attempt_count === 2) {
      stages.push({ ...stage, stage_id: `${stageId}_2`, attempt_index: 2, status: 'failed',
        elapsed_ms: 650, finished_at: iso(start + index * 2 * SECOND + 650), reason_code: 'MODEL_CALL_FAILED' })
    }
  }
  return stages
}

function regenerationConfig(partial: boolean): OpsEffectiveConfig {
  return {
    warning: partial ? null : 2, critical: partial ? null : 4, unit: 'attempts',
    window_seconds: null, source: partial ? null : 'environment',
  }
}

/** 九类链路观测独立于业务运行状态；部分采集不伪造零值或健康状态。 */
function makeSelfMonitoring(now: number, partial: boolean, empty: boolean): OpsSelfMonitoring {
  const metrics: OpsMonitoringMetric[] = [
    { metric_id: 'ingestion_delay', status: 'healthy', value: 120, unit: 'ms',
      observed_at: iso(now - 5 * SECOND), fresh_until: iso(now + MINUTE), unknown_reason: null,
      effective_config: { warning: 1000, critical: 5000, unit: 'ms', window_seconds: 300, source: 'environment' } },
    { metric_id: 'write_failures', status: 'degraded', value: 2, unit: 'events',
      observed_at: iso(now - 5 * SECOND), fresh_until: iso(now + MINUTE), unknown_reason: null,
      effective_config: { warning: 1, critical: 5, unit: 'events', window_seconds: 300, source: 'config_file' } },
    { metric_id: 'dropped_events', status: 'degraded', value: 12, unit: 'events',
      observed_at: iso(now - 5 * SECOND), fresh_until: iso(now + MINUTE), unknown_reason: null,
      effective_config: { warning: 1, critical: 20, unit: 'events', window_seconds: 300, source: 'environment' } },
    { metric_id: 'phoenix_export_backlog', status: 'degraded', value: 24, unit: 'spans',
      observed_at: iso(now - 5 * SECOND), fresh_until: iso(now + MINUTE), unknown_reason: null,
      effective_config: { warning: 20, critical: 100, unit: 'spans', window_seconds: 300, source: 'config_file' } },
    { metric_id: 'alert_evaluation', status: 'healthy', value: 15, unit: 'seconds',
      observed_at: iso(now - 15 * SECOND), fresh_until: iso(now + MINUTE), unknown_reason: null,
      effective_config: { warning: 60, critical: 180, unit: 'seconds', window_seconds: 300, source: 'environment' } },
    { metric_id: 'cleanup', status: 'healthy', value: 3600, unit: 'seconds',
      observed_at: iso(now - HOUR), fresh_until: iso(now + DAY), unknown_reason: null,
      effective_config: { warning: 86400, critical: 172800, unit: 'seconds', window_seconds: 86400, source: 'config_file' } },
    { metric_id: 'notification_failures', status: 'unavailable', value: 5, unit: 'notifications',
      observed_at: iso(now - 5 * SECOND), fresh_until: iso(now + MINUTE), unknown_reason: null,
      effective_config: { warning: 1, critical: 5, unit: 'notifications', window_seconds: 300, source: 'environment' } },
    { metric_id: 'mapping_missing', status: 'degraded', value: 2, unit: 'runs',
      observed_at: iso(now - 5 * SECOND), fresh_until: iso(now + MINUTE), unknown_reason: null,
      effective_config: { warning: 1, critical: 10, unit: 'runs', window_seconds: 300, source: 'config_file' } },
    { metric_id: 'storage_capacity', status: 'degraded', value: 88, unit: 'percent',
      observed_at: iso(now - 5 * SECOND), fresh_until: iso(now + MINUTE), unknown_reason: null,
      effective_config: { warning: 80, critical: 95, unit: 'percent', window_seconds: 300, source: 'environment' } },
  ]
  return {
    metrics: empty ? [] : partial ? metrics.map((metric, index): OpsMonitoringMetric => ({
      ...metric, value: null, status: index % 3 === 1 ? 'monitoring_unavailable' : 'unknown',
      observed_at: index % 3 === 1 ? iso(now - 5 * SECOND) : iso(now - 10 * MINUTE),
      fresh_until: index % 3 === 1 ? iso(now + MINUTE) : iso(now - 5 * MINUTE),
      unknown_reason: index % 3 === 1 ? 'MONITORING_UNAVAILABLE' : 'OBSERVATION_STALE',
      effective_config: index % 3 === 1 ? null : metric.effective_config,
    })) : metrics,
    regeneration_config: regenerationConfig(partial),
  }
}

/** 最终题目各有自己的版本；集合版本不能用来判定任何单题审核有效。 */
function makeReviewVersions(run: OpsRun, partial: boolean): OpsReviewVersions | null {
  if (run.collection_state === 'not_collected') return null
  const requiredScopes = ['correctness', 'curriculum']
  if (partial || run.counts.actual_count === null) return {
    final_content_revision: null, final_questions: null, required_scopes: requiredScopes, evidence: null,
  }
  const finalQuestions = Array.from({ length: run.counts.actual_count }, (_, index) => ({
    question_id: `${run.run_id}_q${index + 1}`, content_revision: `question_revision_${index + 2}`,
  }))
  const evidence: NonNullable<OpsReviewVersions['evidence']> = []
  for (const [index, question] of finalQuestions.entries()) {
    const missingCoverage = (run.review.skipped_count ?? 0) > 0 && index === finalQuestions.length - 1
    for (const scope of requiredScopes) evidence.push({
      ...question, scope,
      // 修改后未重审的题目只保留旧版本证据，旧通过记录不覆盖最终版本。
      content_revision: missingCoverage ? 'question_revision_1' : question.content_revision,
      status: run.quality.reason_codes?.includes('REVIEW_FAILED') && index === 0 && scope === 'correctness'
        ? 'failed' : 'passed',
    })
    // 同时保留历史失败，验证 UI 不以旧证据覆盖最新通过。
    if (index === 0) evidence.push({ ...question, content_revision: 'question_revision_1',
      scope: 'correctness', status: 'failed' })
  }
  return {
    final_content_revision: `batch_revision_${run.revision}`, final_questions: finalQuestions,
    required_scopes: requiredScopes, evidence,
  }
}

function makeDependencies(now: number): OpsDependency[] {
  const kinds: OpsDependency['kind'][] = ['model', 'embedding', 'reranker', 'redis', 'vector_store', 'database', 'phoenix']
  const platform = kinds.map((kind): OpsDependency => {
    const stale = kind === 'reranker'
    const unknown = kind === 'vector_store'
    const failure = kind === 'redis'
    const checked = stale ? now - 10 * MINUTE : now - 10 * SECOND
    return {
      dependency_id: `demo_${kind}`, kind, scope: 'platform', scope_id: 'platform', owner_user_id: null,
      status: stale || unknown ? 'unknown' : failure ? 'unavailable' : kind === 'embedding' ? 'degraded' : 'healthy',
      credential_scope: kind === 'model' || kind === 'embedding' || kind === 'reranker' ? 'platform' : 'none',
      source: unknown ? 'none' : kind === 'model' ? 'passive' : 'probe',
      checked_at: unknown ? null : iso(checked), fresh_until: unknown ? null : iso(checked + 5 * MINUTE),
      last_success_at: unknown ? null : iso(failure ? checked - 5 * MINUTE : checked),
      last_failure_at: unknown || (!failure && !stale) ? null : iso(checked),
      consecutive_failures: unknown ? null : failure || stale ? 3 : 0,
      consecutive_successes: unknown ? null : failure || stale ? 0 : 2,
      error_code: failure ? 'CONNECTION_FAILED' : stale ? 'TIMEOUT' : kind === 'embedding' ? 'SERVICE_ERROR' : null,
      affected_run_count: unknown || stale ? null : failure ? 8 : 0,
      collection_state: unknown ? 'not_collected' : 'complete',
    }
  })
  return [...platform, {
    dependency_id: 'demo_model', kind: 'model', scope: 'account', scope_id: 'demo_user_a', owner_user_id: 'demo_user_a',
    status: 'unavailable', credential_scope: 'personal', source: 'passive', checked_at: iso(now - 20 * SECOND),
    fresh_until: iso(now + 280 * SECOND), last_success_at: iso(now - HOUR), last_failure_at: iso(now - 20 * SECOND),
    consecutive_failures: 3, consecutive_successes: 0, error_code: 'AUTH_INVALID', affected_run_count: 3,
    collection_state: 'complete',
  }]
}

function makeAlert(
  alertId: string, rule: OpsAlert['rule_id'], scope: OpsAlert['scope'], subject: string,
  now: number, options: { owner?: string; first?: number; resolved?: boolean; episode?: number; runs?: string[]; unknown?: boolean } = {},
): OpsAlert {
  const first = options.first ?? now - 30 * MINUTE
  const resolved = options.resolved ?? false
  const scopeId = scope === 'platform' ? 'platform' : scope === 'account' ? options.owner ?? 'demo_user_a' : subject
  return {
    alert_id: alertId, dedupe_key: JSON.stringify([rule, scope, scopeId, subject]), episode_no: options.episode ?? 1,
    rule_id: rule, severity: rule === 'dependency_failure' || rule === 'run_failure' ? 'critical' : 'warning',
    scope, scope_id: scopeId, subject_id: subject, owner_user_id: options.owner ?? null,
    status: resolved ? 'resolved' : 'firing', condition_state: options.unknown ? 'unknown' : resolved ? 'clear' : 'active',
    first_seen_at: iso(first), last_seen_at: iso(resolved ? first + MINUTE : now - MINUTE),
    last_evaluated_at: iso(now), resolved_at: resolved ? iso(first + 2 * MINUTE) : null,
    occurrence_count: rule === 'run_failure' || scope === 'run' ? 1 : 3,
    affected_run_count: options.runs?.length ?? null, sample_run_ids: (options.runs ?? []).slice(0, 5),
    evidence: {
      metric: rule === 'dependency_failure' ? 'consecutive_failures' : rule === 'quality_attention' ? 'attention_rate' : null,
      value: rule === 'dependency_failure' ? 3 : rule === 'quality_attention' ? 0.2 : null,
      numerator: rule === 'quality_attention' ? 2 : null, denominator: rule === 'quality_attention' ? 10 : null,
      threshold: rule === 'dependency_failure' ? 3 : rule === 'quality_attention' ? 0.2 : null,
      window_from: rule === 'quality_attention' ? iso(now - 5 * MINUTE) : null,
      window_to: rule === 'quality_attention' ? iso(now) : null,
      sample_count: rule === 'quality_attention' ? 10 : null,
      reason_code: options.unknown ? 'COLLECTION_GAP' : rule === 'dependency_failure' ? 'CONNECTION_FAILED' : null,
      reason_counts: rule === 'quality_attention' ? { QUANTITY_SHORTFALL: 1, DEGRADED: 1 } : null,
    },
    notification: {
      last_sent_at: iso(resolved ? first + 2 * MINUTE : now - 11 * MINUTE),
      last_kind: rule === 'run_failure' ? 'trigger' : resolved ? 'recovery' : 'reminder',
      next_eligible_at: resolved ? null : iso(now + MINUTE),
    },
    last_transition_reason: resolved ? rule === 'run_failure' ? 'RUN_TERMINATED' : 'RECOVERED' : 'THRESHOLD_EXCEEDED',
  }
}

/** 三条新规则提供可展示的证据、配置与人工排查指引。 */
function makeMonitoringAlerts(now: number, partial: boolean): OpsAlert[] {
  const specifications = [
    { rule: 'monitoring_pipeline_failure', metric: 'phoenix_export_backlog', value: 24,
      warning: 20, critical: 100, unit: 'spans', reason: 'EXPORT_RETRY_EXHAUSTED', owner: 'M2/M3',
      impact: 'Phoenix 导出失败并积压，trace 可用性滞后，业务运行终态保持独立。',
      next: '查看采集与导出链路的失败计数和队列水位，确认导出服务恢复后再核对新观测。' },
    { rule: 'capacity_warning', metric: 'storage_capacity', value: 88,
      warning: 80, critical: 95, unit: 'percent', reason: 'STORAGE_HIGH_WATERMARK', owner: 'M9',
      impact: 'SQL 与 Phoenix 存储使用率达到 warning 水位，继续增长可能影响写入。',
      next: '核对存储空间和清理作业最近成功时间，按运行手册扩容并验证新水位。' },
    { rule: 'notification_failure', metric: 'notification_failures', value: 5,
      warning: 1, critical: 5, unit: 'notifications', reason: 'NOTIFICATION_RETRY_EXHAUSTED', owner: 'M8',
      impact: '运维通知投递重试耗尽，管理员可能无法及时收到异常提醒。',
      next: '查看通知写入与投递失败摘要，排查通知依赖并确认后续轮次能正常投递。' },
  ]
  const alerts = specifications.map((specification): OpsAlert => {
    const alert = makeAlert(`demo_alert_${specification.rule}`, specification.rule, 'platform',
      specification.metric, now, { unknown: partial })
    return {
      ...alert, severity: specification.value >= specification.critical ? 'critical' : 'warning',
      evidence: { ...alert.evidence, metric: specification.metric, value: partial ? null : specification.value,
        threshold: specification.warning, window_from: iso(now - 5 * MINUTE), window_to: iso(now),
        sample_count: partial ? null : 30, reason_code: partial ? 'COLLECTION_GAP' : specification.reason },
      effective_config: { warning: specification.warning, critical: specification.critical,
        unit: specification.unit, window_seconds: 300, source: 'environment' },
      guidance: { impact: specification.impact, owner_module: specification.owner,
        manual_action_required: true, next_step: specification.next },
    }
  })
  if (partial) alerts.push({
    ...makeAlert('demo_alert_unknown_rule', 'future_monitoring_rule', 'platform', 'demo_future_monitor', now,
      { unknown: true }), guidance: null, effective_config: null,
  })
  return alerts
}

/** 每个实例持有独立的通知和 cursor；场景切换不会污染其他实例。 */
export function createDemoOpsClient(scenario: DemoScenario): OpsClient {
  const seedTime = Date.now()
  const partial = scenario === 'partial'
  const empty = scenario === 'empty'
  const runs = empty ? [] : Array.from({ length: 40 }, (_, index) => makeRun(index, seedTime))
  // 活动记录超过默认保留期仍可通过包含 accepted_at 的显式窗口查询。
  if (!empty) {
    const held = makeRun(43, seedTime)
    const accepted = seedTime - 15 * DAY
    runs.push({ ...held, run_id: 'demo_run_held', accepted_at: iso(accepted), started_at: iso(accepted + SECOND),
      heartbeat_at: iso(seedTime - 3 * MINUTE), running_age_ms: seedTime - accepted - SECOND,
      trace: { ...held.trace, group_id: 'demo_run_held', expires_at: iso(accepted + 3 * DAY), availability: 'expired',
        viewer_path: null, reason_code: 'RETENTION_ELAPSED' } })
  }
  const dependencies = empty ? [] : makeDependencies(seedTime)
  const runId = (index: number): string => runs[index]?.run_id ?? 'demo_run_absent'
  const ownerOf = (index: number): string => runs[index]?.owner_user_id ?? 'demo_user_a'
  const associatedRuns = [0, 1, 2, 3, 4, 7, 8, 9].map(runId)
  const alerts: OpsAlert[] = empty ? [] : [
    ...makeMonitoringAlerts(seedTime, partial),
    makeAlert('demo_alert_redis_1', 'dependency_failure', 'platform', 'demo_redis', seedTime,
      { resolved: true, first: seedTime - 4 * HOUR, runs: associatedRuns }),
    makeAlert('demo_alert_redis_2', 'dependency_failure', 'platform', 'demo_redis', seedTime,
      { episode: 2, runs: associatedRuns }),
    makeAlert('demo_alert_personal', 'dependency_failure', 'account', 'demo_model', seedTime,
      { owner: 'demo_user_a', runs: runs.filter(run => run.owner_user_id === 'demo_user_a').slice(0, 3).map(run => run.run_id) }),
    makeAlert('demo_alert_failed', 'run_failure', 'run', runId(2), seedTime,
      { owner: ownerOf(2), resolved: true, runs: [runId(2)] }),
    makeAlert('demo_alert_stale', 'heartbeat_stale', 'run', runId(3), seedTime,
      { owner: ownerOf(3), runs: [runId(3)], unknown: partial }),
    makeAlert('demo_alert_waiting', 'waiting_suspected', 'run', runId(4), seedTime,
      { owner: ownerOf(4), runs: [runId(4)] }),
    makeAlert('demo_alert_old', 'dependency_failure', 'platform', 'demo_embedding', seedTime,
      { resolved: true, first: seedTime - 3 * DAY, runs: [runId(6)] }),
  ]
  // 完整运行关联单独保留；run_id 查询不能只使用至多五个样本。
  const alertRunLinks = new Map(alerts.map(alert => [alert.alert_id,
    alert.subject_id === 'demo_redis' ? [...associatedRuns] : [...alert.sample_run_ids]]))
  let notifications: OpsNotification[] = empty ? [] : [
    { id: 'demo_notification_1', kind: 'ops_alert_trigger', title: '依赖异常', body: '平台依赖出现连续失败，请查看异常轮次。',
      read: false, created_at: iso(seedTime - 5 * MINUTE), ops_alert_id: 'demo_alert_redis_2', ops_episode_no: 2 },
    { id: 'demo_notification_2', kind: 'ops_alert_reminder', title: '依赖异常持续', body: '同一轮次出现新的异常证据。',
      read: false, created_at: iso(seedTime - 3 * MINUTE), ops_alert_id: 'demo_alert_redis_2', ops_episode_no: 2 },
    { id: 'demo_notification_3', kind: 'ops_alert_recovery', title: '依赖已恢复', body: '历史异常轮次已恢复，记录仍在摘要保留期内。',
      read: true, created_at: iso(seedTime - 2 * DAY), ops_alert_id: 'demo_alert_old', ops_episode_no: 1 },
    { id: 'demo_notification_4', kind: 'ops_alert_trigger', title: '出题运行失败', body: '一次运行明确失败，离散故障轮次已关闭。',
      read: false, created_at: iso(seedTime - 20 * MINUTE), ops_alert_id: 'demo_alert_failed', ops_episode_no: 1 },
    { id: 'demo_notification_5', kind: 'bank_ready', title: '演示题库就绪', body: '合成题库已就绪。',
      read: true, created_at: iso(seedTime - HOUR), bank_id: 'demo_bank_1', document_name: null, ops_alert_id: null, ops_episode_no: null },
  ]
  if (partial) {
    const run = runs.find(item => item.execution_status === 'unknown')
    if (run) run.collection_state = 'partial'
  }
  const cursors = new Map<string, Cursor>()
  let cursorSequence = 0

  async function ready(signal: AbortSignal): Promise<number> {
    await delay(signal, scenario === 'loading' ? 2000 : 0)
    signal.throwIfAborted()
    if (scenario === 'error') throw new ApiError('运维摘要暂不可用', 'OPS_DATA_UNAVAILABLE', 503)
    return Date.now()
  }

  function meta(now: number, hasMissing = false): OpsMeta {
    return {
      schema_version: 'v1', generated_at: iso(now), data_state: partial || hasMissing ? 'partial' : 'complete',
      warnings: partial ? [{ code: 'COLLECTION_GAP', message: '演示：采集存在缺口，未知字段和不完整统计不能推断为零。' }]
        : hasMissing ? [{ code: 'HISTORICAL_NOT_COLLECTED', message: '部分合成历史记录未采集，相关未知指标已排除。' }] : [],
    }
  }

  function selection(endpoint: Endpoint, query: OpsQuery, now: number): Selection {
    checkQuery(endpoint, query)
    const limit = query.limit === undefined ? 20 : Number(query.limit)
    // 不再引用已过期 cursor；未知 cursor 与筛选不符统一返回 422。
    for (const [key, value] of cursors) if (now - value.createdAt > CURSOR_LIFETIME) cursors.delete(key)
    if (query.cursor !== undefined) {
      const cursor = cursors.get(String(query.cursor))
      if (!cursor || cursor.endpoint !== endpoint) return invalidQuery()
      // 页面回传首屏实际窗口与继续省略默认窗口等价；显式改窗仍改变签名。
      const window = query.from === undefined && query.to === undefined ? cursor.window
        : makeWindow(endpoint, {
          ...query, from: query.from ?? cursor.window?.from, to: query.to ?? cursor.window?.to,
        }, now)
      const signature = querySignature(query, window, limit)
      if (cursor.signature !== signature) return invalidQuery()
      return { asOf: cursor.asOf, window: cursor.window, cursor, signature, limit }
    }
    const window = makeWindow(endpoint, query, now)
    return { asOf: iso(now), window, signature: querySignature(query, window, limit), limit }
  }

  function paginate<T>(
    endpoint: Endpoint, items: T[], selected: Selection, now: number,
    key: (item: T) => [string, string], ascending = false,
  ): OpsPage<T> {
    const compare = (left: [string, string], right: [string, string]): number => {
      const order = left[0] < right[0] ? -1 : left[0] > right[0] ? 1
        : left[1] < right[1] ? -1 : left[1] > right[1] ? 1 : 0
      return ascending ? order : -order
    }
    const cursor = selected.cursor
    const ordered = [...items].sort((left, right) => compare(key(left), key(right)))
      .filter(item => cursor === undefined || compare(key(item), cursor.anchor) > 0)
    const pageItems = ordered.slice(0, selected.limit)
    const hasMore = ordered.length > selected.limit
    let nextCursor: string | null = null
    const last = pageItems[pageItems.length - 1]
    if (hasMore && last !== undefined) {
      nextCursor = `demo_cursor_${++cursorSequence}`
      cursors.set(nextCursor, {
        endpoint, signature: selected.signature, asOf: selected.asOf, window: selected.window,
        anchor: key(last), createdAt: cursor?.createdAt ?? now,
      })
    }
    return structuredClone({
      ...meta(now), items: pageItems,
      page: { limit: selected.limit, has_more: hasMore, next_cursor: nextCursor, as_of: selected.asOf },
      ...(selected.window ? { window: selected.window } : {}),
      ...(endpoint === 'dependencies' ? { observation_window_seconds: 300 } : {}),
    })
  }

  function currentRun(run: OpsRun, now: number): OpsRun {
    const result = structuredClone(run)
    if (result.execution_status === 'running' && result.started_at !== null) result.running_age_ms = now - Date.parse(result.started_at)
    if (result.observation_flags !== null) result.observation_checked_at = iso(now)
    if (result.trace.availability === 'available') {
      // 演示只模拟单条查询证据；不会实际访问 Phoenix。
      if (result.trace.expires_at !== null && Date.parse(result.trace.expires_at) <= now) {
        result.trace.availability = 'expired'
        result.trace.reason_code = 'RETENTION_ELAPSED'
        result.trace.viewer_path = null
      } else result.trace.verified_at = iso(now)
    }
    return result
  }

  function overview(query: OpsQuery, now: number): OpsOverview {
    const selected = selection('overview', query, now)
    if (!selected.window) return invalidQuery()
    const cohort = runs.filter(run => matchesOwner(run, query) && inWindow(run.accepted_at, selected.window))
    const observed = cohort.filter(run => run.collection_state === 'complete' || run.collection_state === 'partial')
    const completed = observed.filter(run => run.execution_status === 'completed')
    const isKnown = (run: OpsRun) => run.collection_state === 'complete' || run.collection_state === 'partial'
    const executionCounts: OpsOverview['execution']['counts'] = {
      accepted: 0, running: 0, completed: 0, failed: 0, cancelled: 0, unknown: 0,
    }
    for (const status of EXECUTION_STATUSES) executionCounts[status] = cohort.filter(run => run.execution_status === status).length

    function metric(source: OpsRun[], known: (run: OpsRun) => boolean, hit: (run: OpsRun) => boolean): OpsRate {
      const samples = source.filter(run => isKnown(run) && known(run))
      const numerator = samples.filter(hit).length
      const denominator = samples.length
      const uncollected = source.length > 0 && samples.length === 0
      return {
        numerator: uncollected ? null : numerator, denominator: uncollected ? null : denominator,
        value: denominator ? numerator / denominator : null,
        excluded_unknown: source.length - denominator,
        reason: partial ? 'incomplete' : uncollected
          ? source.every(run => !isKnown(run)) ? 'not_collected' : 'incomplete'
          : denominator === 0 ? 'no_samples' : null,
      }
    }
    // completed 中未采集的记录仍计入 excluded_unknown，不进入任何比率分母。
    const allCompleted = cohort.filter(run => run.execution_status === 'completed')
    const coverageSamples = completed.filter(run => {
      const review = run.review
      return review.eligible_count !== null && review.eligible_count > 0 && review.covered_count !== null
        && review.passed_count !== null && review.skipped_count !== null && review.unknown_count !== null
    })
    const eligible = coverageSamples.reduce((sum, run) => sum + (run.review.eligible_count ?? 0), 0)
    const covered = coverageSamples.reduce((sum, run) => sum + (run.review.covered_count ?? 0), 0)
    const regenSamples = completed.filter(run => run.regeneration.attempt_count !== null)
    const timeSamples = regenSamples.filter(run => run.regeneration.total_attempt_ms !== null)
    const currentRuns = runs.filter(run => matchesOwner(run, query))
    const activeAlerts = alerts.filter(alert => {
      if (alert.status !== 'firing' || !exact(query, 'owner_user_id', alert.owner_user_id)) return false
      if (query.entrypoint === undefined) return true
      const linked = alertRunLinks.get(alert.alert_id) ?? []
      return linked.some(link => currentRuns.some(run => run.run_id === link))
        && !(alert.scope === 'platform' && alert.rule_id === 'dependency_failure')
    })
    const missing = cohort.some(run => run.collection_state !== 'complete')
    return {
      ...meta(now, missing), scope: 'sdk_agent_runs_v1', window: selected.window,
      self_monitoring: makeSelfMonitoring(now, partial, empty),
      collection: {
        started_at: iso(seedTime - 16 * DAY), coverage_state: partial || missing ? 'partial' : 'complete',
        observed_runs: cohort.length, partial_runs: cohort.filter(run => run.collection_state === 'partial').length,
        excluded_legacy_records: partial ? null : 0,
        unknown_status_runs: cohort.filter(run => run.execution_status === 'unknown').length,
      },
      execution: {
        counts: executionCounts,
        completion_rate: metric(cohort.filter(run => run.execution_status === 'completed' || run.execution_status === 'failed' || run.execution_status === 'unknown'),
          run => run.execution_status === 'completed' || run.execution_status === 'failed', run => run.execution_status === 'completed'),
      },
      quality_metrics: {
        shortfall_rate: metric(allCompleted, run => run.counts.quantity_status !== 'unknown', run => run.counts.quantity_status === 'shortfall'),
        review_skip_rate: metric(allCompleted.filter(run => run.review.eligible_count !== 0),
          run => run.review.eligible_count !== null && run.review.eligible_count > 0 && run.review.skipped_count !== null,
          run => run.review.skipped_count !== null && run.review.skipped_count > 0),
        degraded_rate: metric(allCompleted, run => run.degradation.occurred !== null, run => run.degradation.occurred === true),
        attention_rate: metric(allCompleted, run => run.quality.status === 'met' || run.quality.status === 'attention', run => run.quality.status === 'attention'),
        review_coverage_rate: {
          numerator: covered, denominator: eligible, value: eligible ? covered / eligible : null,
          excluded_unknown: allCompleted.length - coverageSamples.length,
          reason: partial ? 'incomplete' : eligible === 0 ? allCompleted.length ? 'not_collected' : 'no_samples' : null,
        },
      },
      regeneration_metrics: {
        run_rate: metric(allCompleted, run => run.regeneration.attempt_count !== null,
          run => run.regeneration.attempt_count !== null && run.regeneration.attempt_count > 0),
        attempt_total: regenSamples.length ? regenSamples.reduce((sum, run) => sum + (run.regeneration.attempt_count ?? 0), 0) : allCompleted.length ? null : 0,
        total_attempt_ms: timeSamples.length ? timeSamples.reduce((sum, run) => sum + (run.regeneration.total_attempt_ms ?? 0), 0) : allCompleted.length ? null : 0,
        sample_runs: regenSamples.length,
      },
      current: {
        as_of: iso(now), accepted_count: currentRuns.filter(run => run.execution_status === 'accepted').length,
        running_count: currentRuns.filter(run => run.execution_status === 'running').length,
        suspected_count: currentRuns.filter(run => (run.execution_status === 'accepted' || run.execution_status === 'running' || run.execution_status === 'unknown')
          && (run.observation_flags?.length ?? 0) > 0).length,
        active_alert_count: activeAlerts.length,
      },
      retention: {
        trace_days: 3, summary_days: 14, cleanup_interval_hours: 24, last_cleanup_at: iso(seedTime - HOUR),
        last_cleanup_status: 'success',
      },
    }
  }

  return {
    async getOverview(query, signal) {
      return overview(query, await ready(signal))
    },
    async listRuns(query, signal) {
      const now = await ready(signal)
      const selected = selection('runs', query, now)
      const items = runs.map(run => currentRun(run, now)).filter(run => matchesRun(run, query, selected.window)
        && Date.parse(run.accepted_at) <= Date.parse(selected.asOf))
      return paginate('runs', items, selected, now, run => [run.accepted_at, run.run_id])
    },
    async getRun(runId, signal) {
      const now = await ready(signal)
      const run = runs.find(item => item.run_id === runId)
      if (!run) throw new ApiError('运行摘要不存在或已过保留期', 'OPS_RUN_NOT_FOUND', 404)
      const current = currentRun(run, now)
      return {
        ...meta(now, current.collection_state !== 'complete'), run: current, stages: makeStages(current),
        review_versions: makeReviewVersions(current, partial), regeneration_config: regenerationConfig(partial),
      }
    },
    async listDependencies(query, signal) {
      const now = await ready(signal)
      const selected = selection('dependencies', query, now)
      const scope = query.scope ?? (query.owner_user_id !== undefined ? 'account' : 'platform')
      const items = dependencies.map((dependency): OpsDependency => ({
        ...dependency, status: dependency.fresh_until !== null && Date.parse(dependency.fresh_until) <= now ? 'unknown' : dependency.status,
      })).filter(dependency => dependency.scope === scope && exact(query, 'owner_user_id', dependency.owner_user_id)
        && exact(query, 'kind', dependency.kind) && exact(query, 'status', dependency.status))
      const result = paginate('dependencies', items, selected, now, dependency => [dependency.dependency_id, dependency.scope_id], true)
      if (items.some(item => item.checked_at !== null && item.fresh_until !== null && Date.parse(item.fresh_until) <= now)) {
        result.warnings.push({ code: 'OBSERVATION_STALE', message: '部分依赖观测已过新鲜度窗口，显示为未知。' })
      }
      return result
    },
    async listAlerts(query, signal) {
      const now = await ready(signal)
      const selected = selection('alerts', query, now)
      const items = alerts.filter(alert => inWindow(alert.first_seen_at, selected.window)
        && Date.parse(alert.first_seen_at) <= Date.parse(selected.asOf)
        && exact(query, 'alert_id', alert.alert_id) && exact(query, 'status', alert.status)
        && exact(query, 'rule_id', alert.rule_id) && exact(query, 'severity', alert.severity)
        && exact(query, 'scope', alert.scope) && exact(query, 'owner_user_id', alert.owner_user_id)
        && (query.run_id === undefined || alertRunLinks.get(alert.alert_id)?.some(run => run === query.run_id) === true))
      return paginate('alerts', items, selected, now, alert => [alert.first_seen_at, alert.alert_id])
    },
    async listNotifications(signal) {
      await ready(signal)
      return { unread_count: notifications.filter(item => !item.read).length,
        items: structuredClone([...notifications].sort((left, right) => right.created_at.localeCompare(left.created_at))) }
    },
    async markNotificationsRead(ids, signal) {
      await ready(signal)
      notifications = notifications.map(item => ids.length === 0 || ids.includes(item.id) ? { ...item, read: true } : item)
    },
    async deleteNotification(id, signal) {
      await ready(signal)
      if (!notifications.some(item => item.id === id)) throw new ApiError('通知不存在', 'NOTIFICATION_NOT_FOUND', 404)
      notifications = notifications.filter(item => item.id !== id)
    },
    async openTrace(_path): Promise<OpsTraceAccessResult> {
      // 仅模拟访问决策；即使模拟成功也不打开正文或发出网络请求。
      switch (scenario) {
        case 'trace_denied': return { status: 'denied', message: '演示：追踪正文的独立授权被拒绝。' }
        case 'trace_audit_failed': return { status: 'audit_failed', message: '演示：访问审计写入失败，正文访问已阻止。' }
        case 'trace_expired': return { status: 'expired', message: '演示：打开前重新校验发现追踪正文已过期。' }
        default: return { status: 'simulated_success', message: '演示：独立授权与审计模拟成功，仅展示合成反馈，不打开正文。' }
      }
    },
  }
}
