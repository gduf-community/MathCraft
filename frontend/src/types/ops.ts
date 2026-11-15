/** 管理员 V2 只读运行契约；以 backend/app/schemas/ops.py 为准。 */
export const opsStatuses = ['accepted', 'running', 'completed', 'failed', 'canceled', 'unknown'] as const
export type OpsStatus = typeof opsStatuses[number]
export const opsEntrypoints = ['parameterized', 'conversation'] as const
export type OpsEntrypoint = typeof opsEntrypoints[number]
export const opsErrorCodes = [
  'NEED_CONFIRM', 'MODEL_ERROR', 'RETRIEVAL_ERROR', 'GENERATION_ERROR',
  'NO_PERSISTABLE_QUESTIONS', 'PERSISTENCE_ERROR', 'TASK_SUBMISSION_ERROR',
  'EXECUTION_ERROR', 'USER_CANCELED', 'EXECUTION_INTERRUPTED', 'OUTCOME_UNKNOWN', 'UNKNOWN',
] as const
export type OpsErrorCode = typeof opsErrorCodes[number]

export interface OpsFilters {
  from?: string
  to?: string
  owner_user_id?: string
  entrypoint?: OpsEntrypoint
  status?: OpsStatus
  session_id?: string
  task_id?: string
  batch_id?: string
}
export interface OpsQuery extends OpsFilters {
  limit?: number
  offset?: number
}
export interface OpsMeta {
  schema_version: 'v2'
  generated_at: string
}
export interface OpsWindow {
  from: string
  to: string
  time_basis: 'accepted_at'
}
export interface OpsRun {
  run_id: string
  entrypoint: OpsEntrypoint
  owner_user_id: string
  session_id: string | null
  task_id: string | null
  bank_id: string | null
  document_id: string | null
  batch_id: string | null
  status: OpsStatus
  requested_count: number | null
  delivered_count: number | null
  error_code: OpsErrorCode | null
  accepted_at: string
  started_at: string | null
  finished_at: string | null
  last_observed_at: string | null
}
export interface OpsOverview extends OpsMeta {
  window: OpsWindow
  total_runs: number
  status_counts: Record<OpsStatus, number>
  recent_runs: OpsRun[]
}
export interface OpsPage {
  limit: number
  offset: number
  has_more: boolean
}
export interface OpsRuns extends OpsMeta {
  window: OpsWindow
  items: OpsRun[]
  page: OpsPage
}
export interface OpsRunDetail extends OpsMeta {
  run: OpsRun
}
export interface OpsClient {
  getOverview(query: OpsFilters, signal: AbortSignal): Promise<OpsOverview>
  listRuns(query: OpsQuery, signal: AbortSignal): Promise<OpsRuns>
  getRun(runId: string, signal: AbortSignal): Promise<OpsRunDetail>
}
