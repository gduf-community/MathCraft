/** 运维 v1 联调契约；未知证据使用 null，不映射成零或成功。 */
export type OpsQuery = Record<string, string | number | undefined>
export type OpsCollectionState = 'complete' | 'partial' | 'not_collected' | 'unknown'
export type OpsExecutionStatus = 'accepted' | 'running' | 'completed' | 'failed' | 'cancelled' | 'unknown'
export type OpsEntrypoint = 'parameterized' | 'conversation'
export type OpsObservationFlag = 'waiting_suspected' | 'long_running_suspected' | 'heartbeat_stale'
export type OpsStageName = 'preparing' | 'retrieval' | 'generation' | 'review' | 'repair' | 'persisting' | 'finalizing' | 'unknown'
export type OpsQualityReason = 'QUANTITY_SHORTFALL' | 'REVIEW_SKIPPED' | 'REVIEW_FAILED' | 'DEGRADED'
export type OpsAlertRule = 'dependency_failure' | 'waiting_suspected' | 'long_running_suspected' | 'heartbeat_stale' | 'run_failure' | 'quality_attention'

export interface OpsMeta {
  schema_version: 'v1'
  generated_at: string
  data_state: 'complete' | 'partial'
  warnings: { code: string; message: string }[]
}

export interface OpsWindow {
  from: string
  to: string
  time_basis: 'accepted_at' | 'first_seen_at'
}

export interface OpsRate {
  numerator: number | null
  denominator: number | null
  value: number | null
  excluded_unknown: number | null
  reason: 'no_samples' | 'not_collected' | 'incomplete' | null
}

export interface OpsOverview extends OpsMeta {
  scope: 'sdk_agent_runs_v1'
  window: OpsWindow
  collection: {
    started_at: string | null
    coverage_state: 'complete' | 'partial' | 'unknown'
    observed_runs: number | null
    partial_runs: number | null
    excluded_legacy_records: number | null
    unknown_status_runs: number | null
  }
  execution: {
    counts: Record<OpsExecutionStatus, number | null>
    completion_rate: OpsRate
  }
  quality_metrics: {
    shortfall_rate: OpsRate
    review_skip_rate: OpsRate
    degraded_rate: OpsRate
    attention_rate: OpsRate
    review_coverage_rate: OpsRate
  }
  regeneration_metrics: {
    run_rate: OpsRate
    attempt_total: number | null
    total_attempt_ms: number | null
    sample_runs: number | null
  }
  current: {
    as_of: string
    accepted_count: number | null
    running_count: number | null
    suspected_count: number | null
    active_alert_count: number | null
  }
  retention: {
    trace_days: number
    summary_days: number
    cleanup_interval_hours: number
    last_cleanup_at: string | null
    last_cleanup_status: 'success' | 'failed' | 'unknown'
  }
}

export interface OpsRun {
  run_id: string
  owner_user_id: string
  entrypoint: OpsEntrypoint
  session_id: string | null
  batch_id: string | null
  revision: number
  collection_state: OpsCollectionState
  unknown_fields: string[]
  execution_status: OpsExecutionStatus
  execution_reason_code: 'MODEL_CALL_FAILED' | 'TOOL_FAILED' | 'DEPENDENCY_FAILED' | 'PERSIST_FAILED' | 'USER_CANCELLED' | 'INTERNAL_ERROR' | 'UNKNOWN' | null
  accepted_at: string
  started_at: string | null
  finished_at: string | null
  heartbeat_at: string | null
  updated_at: string | null
  wait_ms: number | null
  elapsed_ms: number | null
  running_age_ms: number | null
  current_stage: 'queued' | OpsStageName
  observation_flags: OpsObservationFlag[] | null
  observation_checked_at: string | null
  observation_unknown_reason: string | null
  counts: {
    target_count: number | null
    actual_count: number | null
    quantity_status: 'met' | 'shortfall' | 'unknown'
  }
  review: {
    required: boolean | null
    eligible_count: number | null
    covered_count: number | null
    passed_count: number | null
    skipped_count: number | null
    unknown_count: number | null
    coverage_rate: number | null
    coverage_reason: 'not_required' | 'empty_output' | 'not_collected' | 'incomplete' | null
    status: 'complete' | 'partial' | 'skipped' | 'not_required' | 'unknown'
  }
  quality: { status: 'met' | 'attention' | 'not_evaluated' | 'unknown'; reason_codes: OpsQualityReason[] | null }
  degradation: { occurred: boolean | null; reason_codes: string[] | null }
  regeneration: {
    attempt_count: number | null
    succeeded_count: number | null
    failed_count: number | null
    in_flight_count: number | null
    total_attempt_ms: number | null
  }
  trace: {
    sdk_trace_id: string | null
    phoenix_trace_id: string | null
    group_id: string | null
    export_status: 'not_started' | 'pending' | 'submitted' | 'failed' | 'dropped' | 'unknown'
    availability: 'available' | 'pending' | 'expired' | 'not_found' | 'unavailable' | 'forbidden' | 'not_collected' | 'unknown'
    complete: boolean | null
    verified_at: string | null
    reason_code: string | null
    expires_at: string | null
    viewer_path: string | null
  }
}

export interface OpsStage {
  stage_id: string
  parent_stage_id: string | null
  name: OpsStageName
  attempt_index: number
  status: 'running' | 'completed' | 'failed' | 'skipped' | 'unknown'
  started_at: string | null
  finished_at: string | null
  elapsed_ms: number | null
  reason_code: string | null
}

export interface OpsRunDetail extends OpsMeta {
  run: OpsRun
  stages: OpsStage[] | null
}

export interface OpsDependency {
  dependency_id: string
  kind: 'model' | 'embedding' | 'reranker' | 'redis' | 'vector_store' | 'database' | 'phoenix'
  scope: 'platform' | 'account'
  scope_id: string
  owner_user_id: string | null
  status: 'healthy' | 'degraded' | 'unavailable' | 'unknown'
  credential_scope: 'platform' | 'personal' | 'none' | 'unknown'
  source: 'passive' | 'probe' | 'mixed' | 'none'
  checked_at: string | null
  fresh_until: string | null
  last_success_at: string | null
  last_failure_at: string | null
  consecutive_failures: number | null
  consecutive_successes: number | null
  error_code: string | null
  affected_run_count: number | null
  collection_state: OpsCollectionState
}

export interface OpsAlert {
  alert_id: string
  dedupe_key: string
  episode_no: number
  rule_id: OpsAlertRule
  severity: 'warning' | 'critical'
  scope: 'platform' | 'account' | 'run'
  scope_id: string
  subject_id: string
  owner_user_id: string | null
  status: 'firing' | 'resolved'
  condition_state: 'active' | 'clear' | 'unknown'
  first_seen_at: string
  last_seen_at: string
  last_evaluated_at: string
  resolved_at: string | null
  occurrence_count: number
  affected_run_count: number | null
  sample_run_ids: string[]
  evidence: {
    metric: string | null
    value: number | null
    numerator: number | null
    denominator: number | null
    threshold: number | null
    window_from: string | null
    window_to: string | null
    sample_count: number | null
    reason_code: string | null
    reason_counts: Partial<Record<OpsQualityReason, number>> | null
  }
  notification: {
    last_sent_at: string | null
    last_kind: 'trigger' | 'reminder' | 'recovery' | null
    next_eligible_at: string | null
  }
  last_transition_reason: string | null
}

export interface OpsPage<T> extends OpsMeta {
  items: T[]
  page: { limit: number; has_more: boolean; next_cursor: string | null; as_of: string }
  window?: OpsWindow
  observation_window_seconds?: number
}

/** 保持现有通知字段；运维通知必须携带轮次关联，普通通知可无关联。 */
export interface OpsNotification {
  id: string
  kind: 'bank_ready' | 'bank_failed' | 'ops_alert_trigger' | 'ops_alert_reminder' | 'ops_alert_recovery'
  title: string
  body: string
  read: boolean
  created_at: string
  bank_id?: string | null
  document_name?: string | null
  ops_alert_id: string | null
  ops_episode_no: number | null
}

export interface OpsNotifications {
  unread_count: number
  items: OpsNotification[]
}

export interface OpsClient {
  getOverview(query: OpsQuery, signal: AbortSignal): Promise<OpsOverview>
  listRuns(query: OpsQuery, signal: AbortSignal): Promise<OpsPage<OpsRun>>
  getRun(runId: string, signal: AbortSignal): Promise<OpsRunDetail>
  listDependencies(query: OpsQuery, signal: AbortSignal): Promise<OpsPage<OpsDependency>>
  listAlerts(query: OpsQuery, signal: AbortSignal): Promise<OpsPage<OpsAlert>>
  listNotifications(signal: AbortSignal): Promise<OpsNotifications>
  markNotificationsRead(ids: string[], signal: AbortSignal): Promise<void>
  deleteNotification(id: string, signal: AbortSignal): Promise<void>
  openTrace(path: string): void
}
