/** V2 只读查询；复用认证会话，外部响应从 unknown 逐项校验。 */
import { opsEntrypoints, opsErrorCodes, opsStatuses } from '../types/ops'
import type {
  OpsClient, OpsMeta, OpsOverview, OpsQuery, OpsRun, OpsRunDetail, OpsRuns, OpsWindow,
} from '../types/ops'
import { ApiError, request } from './session'

const BASE = '/api/admin/ops'
const identifier = /^[A-Za-z0-9_.:-]{1,128}$/
const timestamp = /^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$/

function invalid(): never {
  throw new ApiError('运行响应格式无效，请刷新或联系管理员', 'INVALID_OPS_RESPONSE')
}
function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return invalid()
  return Object.fromEntries(Object.entries(value))
}
function choice<T extends string>(value: unknown, options: readonly T[]): T {
  for (const option of options) if (option === value) return option
  return invalid()
}
function id(value: unknown): string {
  return typeof value === 'string' && identifier.test(value) ? value : invalid()
}
function integer(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= minimum && value <= maximum
    ? value : invalid()
}
function time(value: unknown): string {
  return typeof value === 'string' && timestamp.test(value) && Number.isFinite(Date.parse(value))
    ? value : invalid()
}
function nullable<T>(value: unknown, parse: (value: unknown) => T): T | null {
  return value === null ? null : parse(value)
}
function runs(value: unknown): OpsRun[] {
  if (!Array.isArray(value)) return invalid()
  const result = value.map(parseOpsRun)
  if (new Set(result.map(run => run.run_id)).size !== result.length) return invalid()
  return result
}
function meta(item: Record<string, unknown>): OpsMeta {
  return { schema_version: choice(item.schema_version, ['v2']), generated_at: time(item.generated_at) }
}
function windowValue(value: unknown): OpsWindow {
  const item = object(value)
  const from = time(item.from), to = time(item.to)
  if (Date.parse(from) >= Date.parse(to)) return invalid()
  return { from, to, time_basis: choice(item.time_basis, ['accepted_at']) }
}

export function parseOpsRun(value: unknown): OpsRun {
  const item = object(value)
  return {
    run_id: id(item.run_id), entrypoint: choice(item.entrypoint, opsEntrypoints),
    owner_user_id: id(item.owner_user_id), session_id: nullable(item.session_id, id),
    task_id: nullable(item.task_id, id), bank_id: nullable(item.bank_id, id),
    document_id: nullable(item.document_id, id), batch_id: nullable(item.batch_id, id),
    status: choice(item.status, opsStatuses),
    requested_count: nullable(item.requested_count, value => integer(value, 1)),
    delivered_count: nullable(item.delivered_count, integer),
    error_code: nullable(item.error_code, value => choice(value, opsErrorCodes)),
    accepted_at: time(item.accepted_at), started_at: nullable(item.started_at, time),
    finished_at: nullable(item.finished_at, time), last_observed_at: nullable(item.last_observed_at, time),
  }
}
export function parseOpsOverview(value: unknown): OpsOverview {
  const item = object(value)
  const counts = object(item.status_counts)
  const status_counts = {
    accepted: integer(counts.accepted), running: integer(counts.running), completed: integer(counts.completed),
    failed: integer(counts.failed), canceled: integer(counts.canceled), unknown: integer(counts.unknown),
  }
  const total_runs = integer(item.total_runs), recent_runs = runs(item.recent_runs)
  if (Object.values(status_counts).reduce((sum, count) => sum + count, 0) !== total_runs
    || recent_runs.length > Math.min(10, total_runs)) return invalid()
  return { ...meta(item), window: windowValue(item.window), total_runs, status_counts, recent_runs }
}
export function parseOpsRuns(value: unknown): OpsRuns {
  const item = object(value)
  const page = object(item.page)
  const limit = integer(page.limit, 1, 100), offset = integer(page.offset, 0, 2_147_483_647)
  const items = runs(item.items)
  if (typeof page.has_more !== 'boolean' || items.length > limit) return invalid()
  return { ...meta(item), window: windowValue(item.window), items,
    page: { limit, offset, has_more: page.has_more } }
}
export function parseOpsRunDetail(value: unknown): OpsRunDetail {
  const item = object(value)
  return { ...meta(item), run: parseOpsRun(item.run) }
}

function queryString(query: OpsQuery): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value))
  }
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}
/** 固定错误文案，不回显服务端异常或用户输入。 */
async function safeRequest(path: string, signal: AbortSignal, detail = false): Promise<unknown> {
  signal.throwIfAborted()
  try {
    const result = await request<unknown>(path, { signal, cache: 'no-store' })
    signal.throwIfAborted()
    return result
  } catch (error: unknown) {
    signal.throwIfAborted()
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    if (error instanceof ApiError) {
      if (detail && error.status === 404 && error.code === 'OPS_RUN_NOT_FOUND') {
        throw new ApiError('运行记录不存在', 'OPS_RUN_NOT_FOUND', 404)
      }
      if (error.status === 404) throw new ApiError('运行查询接口尚未就绪', 'OPS_API_NOT_READY', 404)
      if (error.status === 503) throw new ApiError('运行数据暂不可用，请稍后重试', 'OPS_DATA_UNAVAILABLE', 503)
      if (error.status === 401) throw new ApiError('登录已失效，请重新登录', 'TOKEN_EXPIRED', 401)
      if (error.status === 403) throw new ApiError('需要管理员权限', 'FORBIDDEN', 403)
      if (error.status === 422) throw new ApiError('查询参数无效，请检查筛选条件', 'VALIDATION_ERROR', 422)
    }
    throw new ApiError('请求失败，请稍后重试', 'OPS_REQUEST_FAILED')
  }
}
export const realOpsClient: OpsClient = {
  async getOverview(query, signal) {
    return parseOpsOverview(await safeRequest(`${BASE}/overview${queryString(query)}`, signal))
  },
  async listRuns(query, signal) {
    return parseOpsRuns(await safeRequest(`${BASE}/runs${queryString(query)}`, signal))
  },
  async getRun(runId, signal) {
    if (!identifier.test(runId)) throw new ApiError('运行 ID 格式无效', 'VALIDATION_ERROR', 422)
    const result = parseOpsRunDetail(await safeRequest(`${BASE}/runs/${encodeURIComponent(runId)}`, signal, true))
    if (result.run.run_id !== runId) return invalid()
    return result
  },
}
