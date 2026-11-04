/** Access 仅在内存；Cookie 由浏览器维护，不广播凭据。 */
import { apiUrl } from './urls'

let accessToken = ''
let expiresAt = 0
let generation = 0
let refreshFlight: Promise<void> | undefined
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
export function getApiToken() { return accessToken }
export function setApiToken(token: string | null, expiresIn = 900) {
  accessToken = token ?? ''
  expiresAt = token ? Date.now() + expiresIn * 1000 : 0
}
export function clearSession(broadcast = true) {
  generation += 1
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
  const config = await response.json() as AuthConfig
  if (!config.csrf_token) throw new ApiError('认证安全配置不可用，请稍后重试')
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
  if (refreshFlight) return refreshFlight
  const started = generation
  refreshFlight = withSessionLock(async () => {
    if (started !== generation) throw new ApiError('会话已结束', 'SESSION_ENDED', 401)
    await fetchAuthConfig()
    const response = await fetch(apiUrl('/api/auth/refresh'), { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken }, body: '{}' })
    if (!response.ok) throw await failure(response)
    const result = await response.json() as { access_token: string; token_type: string; expires_in: number }
    if (started !== generation) throw new ApiError('会话已结束', 'SESSION_ENDED', 401)
    if (!result.access_token || result.token_type.toLowerCase() !== 'bearer') throw new ApiError('认证响应无效')
    setApiToken(result.access_token, result.expires_in)
  }).catch((error: unknown) => {
    clearSession(false)
    throw error
  }).finally(() => { refreshFlight = undefined })
  return refreshFlight
}
export async function ensureSession(): Promise<void> {
  if (accessToken && Date.now() >= expiresAt - 15000) await refreshSession()
  if (!accessToken) throw new ApiError('请重新登录', 'SESSION_ENDED', 401)
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
    // 写请求仅在后端明确声明认证阶段已拒绝执行时重试一次。
    if (error.code === 'ACCESS_TOKEN_EXPIRED') {
      if (accessToken === sentToken) await refreshSession()
      response = await send()
    }
    if (response.status === 401) clearSession()
  }
  if (authenticated && sentGeneration !== generation) throw new ApiError('会话已结束', 'SESSION_ENDED', 401)
  return response
}
export async function request<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
  const response = await sessionFetch(path, init, authenticated)
  if (!response.ok) throw await failure(response)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
export async function logoutSession(): Promise<void> {
  clearSession()
  await withSessionLock(async () => {
    await fetchAuthConfig()
    await request<void>('/api/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, body: '{}' }, false)
  })
}
