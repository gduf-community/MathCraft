/** 运维只读 API：认证复用 session，响应以 unknown 在边界逐项收窄。 */
import type {
  OpsAlert, OpsClient, OpsDependency, OpsMeta, OpsNotification, OpsNotifications,
  OpsOverview, OpsPage, OpsQuery, OpsRate, OpsRun, OpsRunDetail, OpsStage, OpsWindow,
} from '../types/ops'
import { ApiError, request } from './session'

const BASE = '/api/admin/ops'

function invalid(): never {
  throw new ApiError('运维响应格式无效，请刷新或联系管理员', 'INVALID_OPS_RESPONSE')
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return invalid()
  // Object.entries 构造普通对象，不接纳原型链字段。
  return Object.fromEntries(Object.entries(value))
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : invalid()
}

function hasControlCharacter(value: string): boolean {
  return [...value].some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
}

function id(value: unknown): string {
  const result = text(value)
  return result.length > 0 && result.length <= 512 && !/\s/.test(result) && !hasControlCharacter(result)
    ? result : invalid()
}

function code(value: unknown): string {
  const result = text(value)
  return /^[A-Z][A-Z0-9_]{0,99}$/.test(result) ? result : invalid()
}

function bool(value: unknown): boolean {
  return typeof value === 'boolean' ? value : invalid()
}

function number(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : invalid()
}

function integer(value: unknown): number {
  const result = number(value)
  return Number.isSafeInteger(result) ? result : invalid()
}

function positive(value: unknown): number {
  const result = integer(value)
  return result > 0 ? result : invalid()
}

function ratio(value: unknown): number {
  const result = number(value)
  return result <= 1 ? result : invalid()
}

function timestamp(value: unknown): string {
  const result = text(value)
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$/.test(result)) return invalid()
  const parsed = new Date(result)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 19) === result.slice(0, 19)
    ? result : invalid()
}

function nullable<T>(value: unknown, parse: (input: unknown) => T): T | null {
  return value === null ? null : parse(value)
}

function array<T>(value: unknown, parse: (input: unknown) => T): T[] {
  return Array.isArray(value) ? value.map(parse) : invalid()
}

function oneOf<T extends string>(value: unknown, ...options: T[]): T {
  for (const option of options) if (value === option) return option
  return invalid()
}

function collectionState(value: unknown) {
  return oneOf(value, 'complete', 'partial', 'not_collected', 'unknown')
}

function executionStatus(value: unknown) {
  return oneOf(value, 'accepted', 'running', 'completed', 'failed', 'cancelled', 'unknown')
}

function qualityReason(value: unknown) {
  return oneOf(value, 'QUANTITY_SHORTFALL', 'REVIEW_SKIPPED', 'REVIEW_FAILED', 'DEGRADED')
}

function stageName(value: unknown) {
  return oneOf(value, 'preparing', 'retrieval', 'generation', 'review', 'repair', 'persisting', 'finalizing', 'unknown')
}

function meta(value: Record<string, unknown>): OpsMeta {
  return {
    schema_version: oneOf(value.schema_version, 'v1'),
    generated_at: timestamp(value.generated_at),
    data_state: oneOf(value.data_state, 'complete', 'partial'),
    warnings: array(value.warnings, item => {
      const warning = record(item)
      // 文案只用作纯文本，绝不插入 HTML 或回显到异常中。
      return { code: code(warning.code), message: text(warning.message) }
    }),
  }
}

function parseWindow(value: unknown): OpsWindow {
  const item = record(value)
  const result: OpsWindow = {
    from: timestamp(item.from), to: timestamp(item.to),
    time_basis: oneOf(item.time_basis, 'accepted_at', 'first_seen_at'),
  }
  if (Date.parse(result.from) >= Date.parse(result.to)
    || Date.parse(result.to) - Date.parse(result.from) > 14 * 86400000) return invalid()
  return result
}

function rate(value: unknown): OpsRate {
  const item = record(value)
  const result: OpsRate = {
    numerator: nullable(item.numerator, integer), denominator: nullable(item.denominator, integer),
    value: nullable(item.value, ratio), excluded_unknown: nullable(item.excluded_unknown, integer),
    reason: nullable(item.reason, input => oneOf(input, 'no_samples', 'not_collected', 'incomplete')),
  }
  if (result.value !== null && (result.numerator === null || result.denominator === null
    || result.denominator === 0 || result.reason === 'not_collected' || result.reason === 'no_samples')) return invalid()
  if (result.numerator !== null && result.denominator !== null) {
    if (result.numerator > result.denominator) return invalid()
    if (result.denominator === 0 && result.value !== null) return invalid()
    if (result.value !== null
      && Math.abs(result.value - result.numerator / result.denominator) > 0.000001) return invalid()
  }
  return result
}

/** 接受站内相对路径，拒绝协议、网络路径、认证信息及编码绕过。 */
export function isSafeOpsTracePath(path: string): boolean {
  if (!path || path.length > 2048) return false
  let decoded = path
  for (let count = 0; count < 5; count += 1) {
    if (/[\s\\:@]/.test(decoded) || hasControlCharacter(decoded) || decoded.includes('//')) return false
    if (!decoded.includes('%')) break
    try {
      const next = decodeURIComponent(decoded)
      if (next === decoded) return false
      decoded = next
    } catch { return false }
  }
  if (decoded.includes('%') || /[\s\\:@]/.test(decoded) || hasControlCharacter(decoded) || decoded.includes('//')) return false
  const [pathname, rest = ''] = decoded.split('?', 2)
  if (!/^\/?[a-zA-Z0-9._~/-]+$/.test(pathname)
    || pathname.split('/').some(segment => segment === '.' || segment === '..')) return false
  if (decoded.includes('#') || (decoded.match(/\?/g)?.length ?? 0) > 1) return false
  // 仅允许无认证意义的定位参数；无需任何服务地址或凭据配置。
  const allowed = new Set(['project', 'project_id', 'trace_id', 'span_id', 'tab'])
  for (const [key, value] of new URLSearchParams(rest)) {
    if (!allowed.has(key) || !/^[a-zA-Z0-9._~-]+$/.test(value)) return false
  }
  return true
}

export function parseOpsRun(value: unknown): OpsRun {
  const item = record(value)
  const counts = record(item.counts)
  const review = record(item.review)
  const quality = record(item.quality)
  const degradation = record(item.degradation)
  const regeneration = record(item.regeneration)
  const trace = record(item.trace)
  const result: OpsRun = {
    run_id: id(item.run_id), owner_user_id: id(item.owner_user_id),
    entrypoint: oneOf(item.entrypoint, 'parameterized', 'conversation'),
    session_id: nullable(item.session_id, id), batch_id: nullable(item.batch_id, id),
    revision: positive(item.revision), collection_state: collectionState(item.collection_state),
    unknown_fields: array(item.unknown_fields, input => {
      const field = text(input)
      return /^[a-z][a-z0-9_.]*$/.test(field) ? field : invalid()
    }),
    execution_status: executionStatus(item.execution_status),
    execution_reason_code: nullable(item.execution_reason_code, input => oneOf(input,
      'MODEL_CALL_FAILED', 'TOOL_FAILED', 'DEPENDENCY_FAILED', 'PERSIST_FAILED', 'USER_CANCELLED', 'INTERNAL_ERROR', 'UNKNOWN')),
    accepted_at: timestamp(item.accepted_at), started_at: nullable(item.started_at, timestamp),
    finished_at: nullable(item.finished_at, timestamp), heartbeat_at: nullable(item.heartbeat_at, timestamp),
    updated_at: nullable(item.updated_at, timestamp), wait_ms: nullable(item.wait_ms, integer),
    elapsed_ms: nullable(item.elapsed_ms, integer), running_age_ms: nullable(item.running_age_ms, integer),
    current_stage: item.current_stage === 'queued' ? 'queued' : stageName(item.current_stage),
    observation_flags: nullable(item.observation_flags, input => array(input, flag => oneOf(flag,
      'waiting_suspected', 'long_running_suspected', 'heartbeat_stale'))),
    observation_checked_at: nullable(item.observation_checked_at, timestamp),
    observation_unknown_reason: nullable(item.observation_unknown_reason, code),
    counts: {
      target_count: nullable(counts.target_count, positive), actual_count: nullable(counts.actual_count, integer),
      quantity_status: oneOf(counts.quantity_status, 'met', 'shortfall', 'unknown'),
    },
    review: {
      required: nullable(review.required, bool), eligible_count: nullable(review.eligible_count, integer),
      covered_count: nullable(review.covered_count, integer), passed_count: nullable(review.passed_count, integer),
      skipped_count: nullable(review.skipped_count, integer), unknown_count: nullable(review.unknown_count, integer),
      coverage_rate: nullable(review.coverage_rate, ratio),
      coverage_reason: nullable(review.coverage_reason, input => oneOf(input, 'not_required', 'empty_output', 'not_collected', 'incomplete')),
      status: oneOf(review.status, 'complete', 'partial', 'skipped', 'not_required', 'unknown'),
    },
    quality: {
      status: oneOf(quality.status, 'met', 'attention', 'not_evaluated', 'unknown'),
      reason_codes: nullable(quality.reason_codes, input => array(input, qualityReason)),
    },
    degradation: {
      occurred: nullable(degradation.occurred, bool),
      reason_codes: nullable(degradation.reason_codes, input => array(input, code)),
    },
    regeneration: {
      attempt_count: nullable(regeneration.attempt_count, integer),
      succeeded_count: nullable(regeneration.succeeded_count, integer),
      failed_count: nullable(regeneration.failed_count, integer),
      in_flight_count: nullable(regeneration.in_flight_count, integer),
      total_attempt_ms: nullable(regeneration.total_attempt_ms, integer),
    },
    trace: {
      sdk_trace_id: nullable(trace.sdk_trace_id, id), phoenix_trace_id: nullable(trace.phoenix_trace_id, id),
      group_id: nullable(trace.group_id, id),
      export_status: oneOf(trace.export_status, 'not_started', 'pending', 'submitted', 'failed', 'dropped', 'unknown'),
      availability: oneOf(trace.availability, 'available', 'pending', 'expired', 'not_found', 'unavailable', 'forbidden', 'not_collected', 'unknown'),
      complete: nullable(trace.complete, bool), verified_at: nullable(trace.verified_at, timestamp),
      reason_code: nullable(trace.reason_code, code), expires_at: nullable(trace.expires_at, timestamp),
      viewer_path: nullable(trace.viewer_path, input => {
        const path = text(input)
        return isSafeOpsTracePath(path) ? path : invalid()
      }),
    },
  }
  const r = result.review
  if (r.coverage_rate !== null && (r.eligible_count === null || r.eligible_count === 0
    || r.covered_count === null || r.coverage_reason !== null
    || Math.abs(r.coverage_rate - r.covered_count / r.eligible_count) > 0.000001)) return invalid()
  if (r.passed_count !== null && r.covered_count !== null && r.passed_count > r.covered_count) return invalid()
  if (r.eligible_count !== null && r.covered_count !== null && r.skipped_count !== null
    && r.unknown_count !== null && r.covered_count + r.skipped_count + r.unknown_count !== r.eligible_count) return invalid()
  const g = result.regeneration
  if (g.attempt_count !== null && g.succeeded_count !== null && g.failed_count !== null
    && g.in_flight_count !== null && g.succeeded_count + g.failed_count + g.in_flight_count !== g.attempt_count) return invalid()
  // 摘要解析只检查响应内部一致性；追踪时效由打开入口前的 UI 校验处理。
  if (result.trace.viewer_path !== null && (result.trace.availability !== 'available'
    || result.trace.expires_at === null
    || result.trace.verified_at === null)) return invalid()
  return result
}

function parseStage(value: unknown): OpsStage {
  const item = record(value)
  return {
    stage_id: id(item.stage_id), parent_stage_id: nullable(item.parent_stage_id, id),
    name: stageName(item.name), attempt_index: positive(item.attempt_index),
    status: oneOf(item.status, 'running', 'completed', 'failed', 'skipped', 'unknown'),
    started_at: nullable(item.started_at, timestamp), finished_at: nullable(item.finished_at, timestamp),
    elapsed_ms: nullable(item.elapsed_ms, integer), reason_code: nullable(item.reason_code, code),
  }
}

export function parseOpsRunDetail(value: unknown): OpsRunDetail {
  const item = record(value)
  return { ...meta(item), run: parseOpsRun(item.run), stages: nullable(item.stages, input => array(input, parseStage)) }
}

export function parseOpsDependency(value: unknown): OpsDependency {
  const item = record(value)
  const result: OpsDependency = {
    dependency_id: id(item.dependency_id),
    kind: oneOf(item.kind, 'model', 'embedding', 'reranker', 'redis', 'vector_store', 'database', 'phoenix'),
    scope: oneOf(item.scope, 'platform', 'account'), scope_id: id(item.scope_id),
    owner_user_id: nullable(item.owner_user_id, id),
    status: oneOf(item.status, 'healthy', 'degraded', 'unavailable', 'unknown'),
    credential_scope: oneOf(item.credential_scope, 'platform', 'personal', 'none', 'unknown'),
    source: oneOf(item.source, 'passive', 'probe', 'mixed', 'none'),
    checked_at: nullable(item.checked_at, timestamp), fresh_until: nullable(item.fresh_until, timestamp),
    last_success_at: nullable(item.last_success_at, timestamp), last_failure_at: nullable(item.last_failure_at, timestamp),
    consecutive_failures: nullable(item.consecutive_failures, integer),
    consecutive_successes: nullable(item.consecutive_successes, integer),
    error_code: nullable(item.error_code, code), affected_run_count: nullable(item.affected_run_count, integer),
    collection_state: collectionState(item.collection_state),
  }
  if (result.scope === 'platform' ? result.scope_id !== 'platform' || result.owner_user_id !== null
    : result.owner_user_id === null || result.scope_id !== result.owner_user_id) return invalid()
  if (result.status !== 'unknown' && (result.fresh_until === null || result.checked_at === null)) return invalid()
  return result
}

export function parseOpsAlert(value: unknown): OpsAlert {
  const item = record(value)
  const evidence = record(item.evidence)
  const notification = record(item.notification)
  let reasonCounts: OpsAlert['evidence']['reason_counts'] = null
  if (evidence.reason_counts !== null) {
    reasonCounts = {}
    for (const [key, count] of Object.entries(record(evidence.reason_counts))) reasonCounts[qualityReason(key)] = integer(count)
  }
  const result: OpsAlert = {
    alert_id: id(item.alert_id), dedupe_key: text(item.dedupe_key), episode_no: positive(item.episode_no),
    rule_id: oneOf(item.rule_id, 'dependency_failure', 'waiting_suspected', 'long_running_suspected', 'heartbeat_stale', 'run_failure', 'quality_attention'),
    severity: oneOf(item.severity, 'warning', 'critical'), scope: oneOf(item.scope, 'platform', 'account', 'run'),
    scope_id: id(item.scope_id), subject_id: id(item.subject_id), owner_user_id: nullable(item.owner_user_id, id),
    status: oneOf(item.status, 'firing', 'resolved'), condition_state: oneOf(item.condition_state, 'active', 'clear', 'unknown'),
    first_seen_at: timestamp(item.first_seen_at), last_seen_at: timestamp(item.last_seen_at),
    last_evaluated_at: timestamp(item.last_evaluated_at), resolved_at: nullable(item.resolved_at, timestamp),
    occurrence_count: integer(item.occurrence_count), affected_run_count: nullable(item.affected_run_count, integer),
    sample_run_ids: array(item.sample_run_ids, id),
    evidence: {
      metric: nullable(evidence.metric, input => {
        const name = text(input)
        return /^[a-z][a-z0-9_.]{0,99}$/.test(name) ? name : invalid()
      }),
      value: nullable(evidence.value, number), numerator: nullable(evidence.numerator, integer),
      denominator: nullable(evidence.denominator, integer), threshold: nullable(evidence.threshold, number),
      window_from: nullable(evidence.window_from, timestamp), window_to: nullable(evidence.window_to, timestamp),
      sample_count: nullable(evidence.sample_count, integer), reason_code: nullable(evidence.reason_code, code),
      reason_counts: reasonCounts,
    },
    notification: {
      last_sent_at: nullable(notification.last_sent_at, timestamp),
      last_kind: nullable(notification.last_kind, input => oneOf(input, 'trigger', 'reminder', 'recovery')),
      next_eligible_at: nullable(notification.next_eligible_at, timestamp),
    },
    last_transition_reason: nullable(item.last_transition_reason, code),
  }
  if (result.sample_run_ids.length > 5 || (result.status === 'resolved' && result.resolved_at === null)
    || (result.status === 'firing' && result.resolved_at !== null)) return invalid()
  return result
}

export function parseOpsPage<T>(value: unknown, parseItem: (input: unknown) => T): OpsPage<T> {
  const item = record(value)
  const page = record(item.page)
  const result: OpsPage<T> = {
    ...meta(item), items: array(item.items, parseItem),
    page: {
      limit: positive(page.limit), has_more: bool(page.has_more),
      next_cursor: nullable(page.next_cursor, id), as_of: timestamp(page.as_of),
    },
  }
  if (result.page.limit > 100 || result.items.length > result.page.limit
    || result.page.has_more !== (result.page.next_cursor !== null)) return invalid()
  if (item.window !== undefined) result.window = parseWindow(item.window)
  if (item.observation_window_seconds !== undefined) result.observation_window_seconds = positive(item.observation_window_seconds)
  return result
}

export function parseOpsOverview(value: unknown): OpsOverview {
  const item = record(value)
  const collection = record(item.collection)
  const execution = record(item.execution)
  const counts = record(execution.counts)
  const quality = record(item.quality_metrics)
  const regeneration = record(item.regeneration_metrics)
  const current = record(item.current)
  const retention = record(item.retention)
  return {
    ...meta(item), scope: oneOf(item.scope, 'sdk_agent_runs_v1'), window: parseWindow(item.window),
    collection: {
      started_at: nullable(collection.started_at, timestamp),
      coverage_state: oneOf(collection.coverage_state, 'complete', 'partial', 'unknown'),
      observed_runs: nullable(collection.observed_runs, integer), partial_runs: nullable(collection.partial_runs, integer),
      excluded_legacy_records: nullable(collection.excluded_legacy_records, integer),
      unknown_status_runs: nullable(collection.unknown_status_runs, integer),
    },
    execution: {
      counts: {
        accepted: nullable(counts.accepted, integer), running: nullable(counts.running, integer),
        completed: nullable(counts.completed, integer), failed: nullable(counts.failed, integer),
        cancelled: nullable(counts.cancelled, integer), unknown: nullable(counts.unknown, integer),
      },
      completion_rate: rate(execution.completion_rate),
    },
    quality_metrics: {
      shortfall_rate: rate(quality.shortfall_rate), review_skip_rate: rate(quality.review_skip_rate),
      degraded_rate: rate(quality.degraded_rate), attention_rate: rate(quality.attention_rate),
      review_coverage_rate: rate(quality.review_coverage_rate),
    },
    regeneration_metrics: {
      run_rate: rate(regeneration.run_rate), attempt_total: nullable(regeneration.attempt_total, integer),
      total_attempt_ms: nullable(regeneration.total_attempt_ms, integer), sample_runs: nullable(regeneration.sample_runs, integer),
    },
    current: {
      as_of: timestamp(current.as_of), accepted_count: nullable(current.accepted_count, integer),
      running_count: nullable(current.running_count, integer), suspected_count: nullable(current.suspected_count, integer),
      active_alert_count: nullable(current.active_alert_count, integer),
    },
    retention: {
      trace_days: positive(retention.trace_days), summary_days: positive(retention.summary_days),
      cleanup_interval_hours: positive(retention.cleanup_interval_hours), last_cleanup_at: nullable(retention.last_cleanup_at, timestamp),
      last_cleanup_status: oneOf(retention.last_cleanup_status, 'success', 'failed', 'unknown'),
    },
  }
}

export function parseOpsNotifications(value: unknown): OpsNotifications {
  const response = record(value)
  return {
    unread_count: integer(response.unread_count),
    items: array(response.items, input => {
      const item = record(input)
      const kind = oneOf(item.kind, 'bank_ready', 'bank_failed', 'ops_alert_trigger', 'ops_alert_reminder', 'ops_alert_recovery')
      const alertId = item.ops_alert_id === undefined ? null : nullable(item.ops_alert_id, id)
      const episode = item.ops_episode_no === undefined ? null : nullable(item.ops_episode_no, positive)
      if (kind.startsWith('ops_') && (alertId === null || episode === null)) return invalid()
      // 既有题库通知可能使用无时区 ISO 时间，兼容其原有契约。
      const createdAt = text(item.created_at)
      if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/.test(createdAt)
        || !Number.isFinite(Date.parse(createdAt))) return invalid()
      const notification: OpsNotification = {
        id: id(item.id), kind, title: text(item.title), body: text(item.body),
        read: bool(item.read), created_at: createdAt, ops_alert_id: alertId, ops_episode_no: episode,
      }
      if (item.bank_id !== undefined) notification.bank_id = nullable(item.bank_id, id)
      if (item.document_name !== undefined) notification.document_name = nullable(item.document_name, text)
      return notification
    }),
  }
}

function queryString(query: OpsQuery): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value))
  }
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

/** 不信任服务端异常文案，固定安全错误；仅专用 code 表示运行不存在。 */
async function safeRequest(path: string, signal: AbortSignal, init: RequestInit = {}, runDetail = false): Promise<unknown> {
  signal.throwIfAborted()
  try {
    const result = await request<unknown>(path, { ...init, signal, cache: 'no-store' })
    signal.throwIfAborted()
    return result
  } catch (error: unknown) {
    if (signal.aborted) { signal.throwIfAborted(); throw error }
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    if (error instanceof ApiError) {
      if (runDetail && error.status === 404 && error.code === 'OPS_RUN_NOT_FOUND') {
        throw new ApiError('运行摘要不存在或已过保留期', 'OPS_RUN_NOT_FOUND', 404)
      }
      if (error.status === 404 && path.startsWith(BASE)) throw new ApiError('运维接口尚未就绪', 'OPS_API_NOT_READY', 404)
      if (error.status === 503) throw new ApiError('运维摘要暂不可用', 'OPS_DATA_UNAVAILABLE', 503)
      if (error.status === 401) throw new ApiError('登录已失效，请重新登录', 'TOKEN_EXPIRED', 401)
      if (error.status === 403) throw new ApiError('需要管理员权限', 'FORBIDDEN', 403)
      if (error.status === 422) throw new ApiError('查询参数无效，请检查筛选条件', 'VALIDATION_ERROR', 422)
      if (error.status === 404) throw new ApiError('通知不存在', 'NOTIFICATION_NOT_FOUND', 404)
    }
    throw new ApiError('请求失败，请稍后重试', 'OPS_REQUEST_FAILED')
  }
}

export const realOpsClient: OpsClient = {
  async getOverview(query, signal) {
    return parseOpsOverview(await safeRequest(`${BASE}/overview${queryString(query)}`, signal))
  },
  async listRuns(query, signal) {
    return parseOpsPage(await safeRequest(`${BASE}/runs${queryString(query)}`, signal), parseOpsRun)
  },
  async getRun(runId, signal) {
    return parseOpsRunDetail(await safeRequest(`${BASE}/runs/${encodeURIComponent(runId)}`, signal, {}, true))
  },
  async listDependencies(query, signal) {
    const result = parseOpsPage(await safeRequest(`${BASE}/dependencies${queryString(query)}`, signal), parseOpsDependency)
    if (result.observation_window_seconds === undefined) return invalid()
    return result
  },
  async listAlerts(query, signal) {
    return parseOpsPage(await safeRequest(`${BASE}/alerts${queryString(query)}`, signal), parseOpsAlert)
  },
  async listNotifications(signal) {
    return parseOpsNotifications(await safeRequest('/api/notifications', signal))
  },
  async markNotificationsRead(ids, signal) {
    await safeRequest('/api/notifications/read', signal, {
      method: 'POST', body: JSON.stringify({ ids: ids.length ? ids : null }),
    })
  },
  async deleteNotification(notificationId, signal) {
    await safeRequest(`/api/notifications/${encodeURIComponent(notificationId)}`, signal, { method: 'DELETE' })
  },
  openTrace(path) {
    if (!isSafeOpsTracePath(path)) throw new ApiError('追踪路径无效或包含不安全信息', 'INVALID_TRACE_PATH')
    window.open(path, '_blank', 'noopener,noreferrer')
  },
}
