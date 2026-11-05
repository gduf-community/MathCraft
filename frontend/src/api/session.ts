/** Access 仅在内存；Cookie 由浏览器维护，不广播凭据。 */
import { apiUrl } from './urls'
import type { ApiUser, LoginResult } from './backend'

let accessToken = ''
// 仅用于重试撤销，绝不参与业务认证或刷新；新显式登录成功后才丢弃它。
let pendingLogoutToken = ''
let expiresAt = 0
let generation = 0
let refreshFlight: { generation: number; promise: Promise<void> } | undefined
let principal: { id: string; role: string } | undefined
let csrfToken = ''
const listeners = new Set<() => void>()
const channel = typeof BroadcastChannel === 'undefined' ? undefined : new BroadcastChannel('mathcraft-session')
export interface AuthConfig {
  site_key: string
  csrf_token: string
  available?: boolean
  development_accounts_enabled?: boolean
}
export class ApiError extends Error {
  constructor(message: string, public code = 'REQUEST_FAILED', public status = 0, public retryAfter = 0) { super(message) }
}
function describe(value: unknown): string | undefined {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(describe).filter(Boolean).join('；')
  if (value && typeof value === 'object') {
    const detail = value as Record<string, unknown>
    return describe(detail.message ?? detail.msg ?? detail.detail)
  }
}
async function failure(response: Response): Promise<ApiError> {
  let body: unknown
  try { body = await response.json() } catch { body = undefined }
  const record = body && typeof body === 'object' ? body as Record<string, unknown> : {}
  const detail = record.detail && typeof record.detail === 'object' ? record.detail as Record<string, unknown> : record
  return new ApiError(describe(body) ?? '请求失败（HTTP ' + response.status + '）', typeof detail.code === 'string' ? detail.code : 'REQUEST_FAILED', response.status, Number(response.headers.get('Retry-After')) || 0)
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
function invalidResponse(): never { throw new ApiError('认证响应无效', 'INVALID_AUTH_RESPONSE') }
export function parseApiUser(value: unknown): ApiUser {
  if (!isRecord(value) || typeof value.id !== 'string' || !value.id
    || typeof value.account !== 'string' || !value.account
    || (value.role !== 'teacher' && value.role !== 'student')
    || value.identity !== (value.role === 'teacher' ? '教师' : '学生')
    || typeof value.display_name !== 'string' || !value.display_name.trim()) return invalidResponse()
  const optionalText = (key: string): string | null | undefined => {
    const field = value[key]
    if (field === null || field === undefined || typeof field === 'string') return field
    return invalidResponse()
  }
  return { id: value.id, account: value.account, role: value.role, identity: value.role === 'teacher' ? '教师' : '学生',
    display_name: value.display_name, email: optionalText('email'), user_no: optionalText('user_no'),
    avatar_url: optionalText('avatar_url'), school: optionalText('school'),
    gender: optionalText('gender'), phone: optionalText('phone') }
}
export function parseLoginResult(value: unknown): LoginResult {
  if (!isRecord(value) || typeof value.access_token !== 'string' || !value.access_token.trim()
    || value.token_type !== 'bearer' || typeof value.expires_in !== 'number'
    || !Number.isFinite(value.expires_in) || value.expires_in <= 0
    || !Number.isFinite(Date.now() + value.expires_in * 1000)) return invalidResponse()
  return { access_token: value.access_token, token_type: value.token_type,
    expires_in: value.expires_in, user: parseApiUser(value.user) }
}
function assertCurrent(started: number): void {
  if (started !== generation) throw new ApiError('会话已结束', 'SESSION_ENDED', 401)
}
function installSession(result: LoginResult): void {
  principal = { id: result.user.id, role: result.user.role }
  setApiToken(result.access_token, result.expires_in)
}
/** 显式登录先推进代次，完整解析及映射成功后才原子安装凭据。 */
export async function establishSession<T>(action: () => Promise<unknown>, map: (result: LoginResult) => T): Promise<T> {
  clearSession(false)
  const started = generation
  return withSessionLock(async () => {
    assertCurrent(started)
    const result = parseLoginResult(await action())
    const mapped = map(result)
    assertCurrent(started)
    pendingLogoutToken = ''
    installSession(result)
    return mapped
  })
}
export function getApiToken() { return accessToken }
export function setApiToken(token: string | null, expiresIn = 900) {
  accessToken = token ?? ''
  expiresAt = token ? Date.now() + expiresIn * 1000 : 0
}
export function clearSession(broadcast = true) {
  generation += 1
  principal = undefined
  refreshFlight = undefined
  setApiToken(null)
  for (const listener of listeners) listener()
  if (broadcast) channel?.postMessage({ type: 'invalidate' })
}
channel?.addEventListener('message', event => {
  if (event.data?.type === 'invalidate') clearSession(false)
})
export function onSessionCleared(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
async function fetchAuthConfig(): Promise<AuthConfig> {
  const response = await fetch(apiUrl('/api/auth/config'), { credentials: 'include', cache: 'no-store' })
  if (!response.ok) throw await failure(response)
  const value: unknown = await response.json()
  if (!isRecord(value) || typeof value.site_key !== 'string'
    || typeof value.csrf_token !== 'string' || !value.csrf_token
    || (value.available !== undefined && typeof value.available !== 'boolean')
    || (value.development_accounts_enabled !== undefined && typeof value.development_accounts_enabled !== 'boolean')) return invalidResponse()
  const config: AuthConfig = { site_key: value.site_key, csrf_token: value.csrf_token,
    available: value.available, development_accounts_enabled: value.development_accounts_enabled }
  csrfToken = config.csrf_token
  return config
}
export function getAuthConfig(): Promise<AuthConfig> {
  return withSessionLock(fetchAuthConfig)
}
async function withSessionLock<T>(action: () => Promise<T>): Promise<T> {
  if (!navigator.locks) throw new ApiError('当前浏览器不支持安全会话协调，请使用新版浏览器')
  return navigator.locks.request('mathcraft-refresh', action)
}
export async function refreshSession(): Promise<void> {
  if (pendingLogoutToken) throw new ApiError('注销尚未确认，请重试退出或重新登录', 'SESSION_ENDED', 401)
  if (refreshFlight?.generation === generation) return refreshFlight.promise
  const started = generation
  const expected = principal
  const flight = { generation: started, promise: Promise.resolve() }
  flight.promise = withSessionLock(async () => {
    assertCurrent(started)
    await fetchAuthConfig()
    assertCurrent(started)
    const response = await fetch(apiUrl('/api/auth/refresh'), { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken }, body: '{}' })
    if (!response.ok) throw await failure(response)
    const result = parseLoginResult(await response.json())
    assertCurrent(started)
    if (expected && (expected.id !== result.user.id || expected.role !== result.user.role)) {
      throw new ApiError('其他标签页已切换账号，请重新登录', 'SESSION_IDENTITY_CHANGED', 401)
    }
    installSession(result)
  }).catch((error: unknown) => {
    if (started === generation) clearSession(false)
    throw error
  }).finally(() => { if (refreshFlight === flight) refreshFlight = undefined })
  refreshFlight = flight
  return flight.promise
}
export async function ensureSession(): Promise<void> {
  if (accessToken && Date.now() >= expiresAt - 15000) await refreshSession()
  if (!accessToken) throw new ApiError('请重新登录', 'SESSION_ENDED', 401)
}
/** 为 XHR 等非 fetch 操作复用认证代次保护，只重试明确的过期拒绝。 */
export async function authenticatedOperation<T>(action: (token: string) => Promise<T>): Promise<T> {
  const started = generation
  await ensureSession()
  assertCurrent(started)
  const sentToken = accessToken
  try {
    const result = await action(sentToken)
    assertCurrent(started)
    return result
  } catch (error: unknown) {
    assertCurrent(started)
    if (!(error instanceof ApiError) || error.status !== 401) throw error
    if (error.code !== 'ACCESS_TOKEN_EXPIRED') {
      clearSession()
      throw error
    }
    if (accessToken === sentToken) await refreshSession()
    assertCurrent(started)
    try {
      const result = await action(accessToken)
      assertCurrent(started)
      return result
    } catch (retryError: unknown) {
      assertCurrent(started)
      if (retryError instanceof ApiError && retryError.status === 401) clearSession()
      throw retryError
    }
  }
}
export async function sessionFetch(path: string, init: RequestInit = {}, authenticated = true): Promise<Response> {
  if (authenticated && accessToken && Date.now() >= expiresAt - 15000) await refreshSession()
  if (authenticated && !accessToken) throw new ApiError('请重新登录', 'SESSION_ENDED', 401)
  const sentGeneration = generation
  const sentToken = accessToken
  const send = () => {
    const headers = new Headers(init.headers)
    if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
    if (authenticated && accessToken) headers.set('Authorization', 'Bearer ' + accessToken)
    return fetch(apiUrl(path), { ...init, credentials: 'include', headers })
  }
  let response = await send()
  if (authenticated && response.status === 401 && accessToken) {
    const error = await failure(response.clone())
    assertCurrent(sentGeneration)
    // 写请求仅在后端明确声明认证阶段已拒绝执行时重试一次。
    if (error.code === 'ACCESS_TOKEN_EXPIRED') {
      if (accessToken === sentToken) await refreshSession()
      assertCurrent(sentGeneration)
      response = await send()
    }
    assertCurrent(sentGeneration)
    if (response.status === 401) clearSession()
  }
  if (authenticated && sentGeneration !== generation) throw new ApiError('会话已结束', 'SESSION_ENDED', 401)
  return response
}
export async function request<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
  const started = generation
  const response = await sessionFetch(path, init, authenticated)
  if (!response.ok) throw await failure(response)
  if (response.status === 204) return undefined as T
  const result: T = await response.json()
  if (authenticated) assertCurrent(started)
  return result
}
export async function logoutSession(): Promise<void> {
  // Cookie 跨标签共享，注销必须绑定本标签原始 access sid，不能刷新或匿名注销。
  const token = accessToken || pendingLogoutToken
  pendingLogoutToken = token
  clearSession(false)
  if (!token) return
  const started = generation
  await withSessionLock(async () => {
    assertCurrent(started)
    await fetchAuthConfig()
    assertCurrent(started)
    await request<void>('/api/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken, Authorization: 'Bearer ' + token }, body: '{}' }, false)
    if (pendingLogoutToken === token) pendingLogoutToken = ''
  })
}
