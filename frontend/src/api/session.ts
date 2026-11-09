/** Access 仅在内存；Cookie 由浏览器维护，不广播凭据。 */
import { apiUrl } from './urls'
import type { ApiUser, LoginResult } from './backend'

let accessToken = ''
// 仅用于重试撤销，绝不参与业务认证或刷新；新显式登录成功后才丢弃它。
let pendingLogoutToken = ''
let expiresAt = 0
let generation = 0
let refreshFlight: { generation: number; promise: Promise<void> } | undefined
interface SessionIdentity { id: string; role: string; sid?: string; email?: string }
interface TabState { blocked: boolean; identity?: SessionIdentity }
const tabStateKey = 'mathcraft-session-state'
// 只持久化身份约束和退出意图，不保存任何认证凭据。
function readTabState(): TabState {
  try {
    const raw = sessionStorage.getItem(tabStateKey)
    if (!raw) return { blocked: false }
    const value: unknown = JSON.parse(raw)
    if (!isRecord(value) || typeof value.blocked !== 'boolean') return { blocked: true }
    const identity = value.identity
    if (identity === undefined) return { blocked: value.blocked }
    if (!isRecord(identity) || typeof identity.id !== 'string' || typeof identity.role !== 'string'
      || (identity.sid !== undefined && typeof identity.sid !== 'string')) return { blocked: true }
    return { blocked: value.blocked, identity: { id: identity.id, role: identity.role, sid: identity.sid } }
  } catch { return { blocked: true } }
}
let tabState = readTabState()
let principal: SessionIdentity | undefined
function saveTabState(state: TabState): void {
  tabState = state
  try { sessionStorage.setItem(tabStateKey, JSON.stringify(state)) }
  catch { /* 存储不可用时，下次加载拒绝自动恢复。 */ }
}
function sessionId(token: string): string | undefined {
  // sid 只用于消息路由，不替代服务端的签名或权限校验。
  try {
    const payload: unknown = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return isRecord(payload) && typeof payload.sid === 'string' ? payload.sid : undefined
  } catch { return undefined }
}
let csrfToken = ''
const listeners = new Set<() => void>()
const channel = typeof BroadcastChannel === 'undefined' ? undefined : new BroadcastChannel('mathcraft-session')
export interface AuthConfig {
  admin_contact?: string
  methods?: ('email_code' | 'account_password')[]
  site_key: string
  csrf_token: string
  available?: boolean
  turnstile_enabled: boolean
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
    || (value.role !== 'teacher' && value.role !== 'student' && value.role !== 'admin')
    || value.identity !== (value.role === 'admin' ? '管理员' : value.role === 'teacher' ? '教师' : '学生')
    || (value.password_change_recommended !== undefined && typeof value.password_change_recommended !== 'boolean')
    || typeof value.email_verified !== 'boolean'
    || typeof value.display_name !== 'string' || !value.display_name.trim()) return invalidResponse()
  const optionalText = (key: string): string | null | undefined => {
    const field = value[key]
    if (field === null || field === undefined || typeof field === 'string') return field
    return invalidResponse()
  }
  return { id: value.id, account: value.account, role: value.role, identity: value.role === 'admin' ? '管理员' : value.role === 'teacher' ? '教师' : '学生',
    display_name: value.display_name, email: optionalText('email'), email_verified: value.email_verified, user_no: optionalText('user_no'),
    password_change_recommended: value.password_change_recommended,
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
export function assertCurrentSession(started: number): void {
  if (started !== generation) throw new ApiError('会话已结束', 'SESSION_ENDED', 401)
}
function installSession(result: LoginResult): void {
  principal = { id: result.user.id, role: result.user.role, sid: sessionId(result.access_token), email: result.user.email ?? undefined }
  saveTabState({ blocked: false, identity: { id: principal.id, role: principal.role, sid: principal.sid } })
  setApiToken(result.access_token, result.expires_in)
}
/** 显式登录先推进代次，完整解析及映射成功后才原子安装凭据。 */
export async function establishSession<T>(action: () => Promise<unknown>, map: (result: LoginResult) => T): Promise<T> {
  clearSession(false)
  const started = generation
  return withSessionLock(async () => {
    assertCurrentSession(started)
    const result = parseLoginResult(await action())
    const mapped = map(result)
    assertCurrentSession(started)
    pendingLogoutToken = ''
    installSession(result)
    return mapped
  })
}
export function getApiToken() { return accessToken }
export function getSessionGeneration() { return generation }
export function setApiToken(token: string | null, expiresIn = 900) {
  accessToken = token ?? ''
  expiresAt = token ? Date.now() + expiresIn * 1000 : 0
}
export function clearSession(broadcast = true) {
  const previous = principal ?? tabState.identity
  if (broadcast) saveTabState({ blocked: true, identity: previous })
  generation += 1
  principal = undefined
  refreshFlight = undefined
  setApiToken(null)
  for (const listener of listeners) listener()
  if (broadcast && previous?.sid) channel?.postMessage({ type: 'invalidate', scope: 'session', userId: previous.id, sid: previous.sid } satisfies Invalidation)
}
type Invalidation = { type: 'invalidate'; scope: 'session'; userId: string; sid: string }
  | { type: 'invalidate'; scope: 'user'; userId: string }
  | { type: 'invalidate'; scope: 'email'; email: string }
function matchesInvalidation(value: unknown): value is Invalidation {
  if (!isRecord(value) || value.type !== 'invalidate') return false
  const current = principal ?? tabState.identity
  if (!current) return false
  if (value.scope === 'user') return value.userId === current.id
  if (value.scope === 'session') return value.userId === current.id
    && typeof value.sid === 'string' && value.sid === current.sid
  return value.scope === 'email' && typeof value.email === 'string'
    && value.email.toLowerCase() === principal?.email?.toLowerCase()
}
/** 安全资料修改撤销用户全部会话，密码重置按已验证邮箱通知。 */
export function invalidateUserSessions(email?: string): void {
  const current = principal ?? tabState.identity
  const message: Invalidation | undefined = email
    ? { type: 'invalidate', scope: 'email', email }
    : current ? { type: 'invalidate', scope: 'user', userId: current.id } : undefined
  if (!message) return
  if (matchesInvalidation(message)) {
    saveTabState({ blocked: true, identity: current })
    clearSession(false)
  }
  channel?.postMessage(message)
}
channel?.addEventListener('message', event => {
  if (!matchesInvalidation(event.data)) return
  saveTabState({ blocked: true, identity: principal ?? tabState.identity })
  clearSession(false)
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
    || (value.admin_contact !== undefined && typeof value.admin_contact !== 'string')
    || (value.methods !== undefined && (!Array.isArray(value.methods) || value.methods.some(method => method !== 'email_code' && method !== 'account_password')))
    || (value.available !== undefined && typeof value.available !== 'boolean')
    || (value.turnstile_enabled !== undefined && typeof value.turnstile_enabled !== 'boolean')
    || (value.development_accounts_enabled !== undefined && typeof value.development_accounts_enabled !== 'boolean')) return invalidResponse()
  const methods: NonNullable<AuthConfig['methods']> = []
  if (Array.isArray(value.methods)) {
    for (const method of value.methods) {
      if (method === 'email_code' || method === 'account_password') methods.push(method)
    }
  }
  const config: AuthConfig = { admin_contact: typeof value.admin_contact === 'string' ? value.admin_contact : undefined, methods, site_key: value.site_key, csrf_token: value.csrf_token,
    available: value.available, turnstile_enabled: value.turnstile_enabled ?? true, development_accounts_enabled: value.development_accounts_enabled }
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
  if (pendingLogoutToken || tabState.blocked) throw new ApiError('会话已结束，请重新登录；退出未确认时可重试退出', 'SESSION_ENDED', 401)
  if (refreshFlight?.generation === generation) return refreshFlight.promise
  const started = generation
  const expected = principal ?? tabState.identity
  const flight = { generation: started, promise: Promise.resolve() }
  flight.promise = withSessionLock(async () => {
    assertCurrentSession(started)
    await fetchAuthConfig()
    assertCurrentSession(started)
    const response = await fetch(apiUrl('/api/auth/refresh'), { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken }, body: '{}' })
    if (!response.ok) throw await failure(response)
    const result = parseLoginResult(await response.json())
    assertCurrentSession(started)
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
/** Cookie 写操作与登录/刷新串行；续期在锁外，锁内绝不自动刷新或重放。 */
export async function mutateSessionCookie(
  path: string,
  init: RequestInit,
  authenticated: boolean,
  onSuccess: () => void,
): Promise<void> {
  const started = generation
  if (authenticated) await ensureSession()
  assertCurrentSession(started)
  await withSessionLock(async () => {
    assertCurrentSession(started)
    const headers = new Headers(init.headers)
    headers.set('Content-Type', 'application/json')
    if (authenticated) {
      if (!accessToken) throw new ApiError('请重新登录', 'SESSION_ENDED', 401)
      headers.set('Authorization', 'Bearer ' + accessToken)
    }
    const response = await fetch(apiUrl(path), { ...init, credentials: 'include', headers })
    assertCurrentSession(started)
    if (!response.ok) {
      const error = await failure(response)
      assertCurrentSession(started)
      if (authenticated && error.status === 401 && error.code !== 'ACCESS_TOKEN_EXPIRED') clearSession()
      throw error
    }
    // 清除旧身份也在锁内完成，不能晚于排队的新登录安装。
    onSuccess()
  })
}
/** 为 XHR 等非 fetch 操作复用认证代次保护，只重试明确的过期拒绝。 */
export async function authenticatedOperation<T>(action: (token: string) => Promise<T>): Promise<T> {
  const started = generation
  await ensureSession()
  assertCurrentSession(started)
  const sentToken = accessToken
  try {
    const result = await action(sentToken)
    assertCurrentSession(started)
    return result
  } catch (error: unknown) {
    assertCurrentSession(started)
    if (!(error instanceof ApiError) || error.status !== 401) throw error
    if (error.code !== 'ACCESS_TOKEN_EXPIRED') {
      clearSession()
      throw error
    }
    if (accessToken === sentToken) await refreshSession()
    assertCurrentSession(started)
    try {
      const result = await action(accessToken)
      assertCurrentSession(started)
      return result
    } catch (retryError: unknown) {
      assertCurrentSession(started)
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
    assertCurrentSession(sentGeneration)
    // 写请求仅在后端明确声明认证阶段已拒绝执行时重试一次。
    if (error.code === 'ACCESS_TOKEN_EXPIRED') {
      if (accessToken === sentToken) await refreshSession()
      assertCurrentSession(sentGeneration)
      response = await send()
    }
    assertCurrentSession(sentGeneration)
    if (response.status === 401) clearSession()
  }
  if (authenticated && sentGeneration !== generation) throw new ApiError('会话已结束', 'SESSION_ENDED', 401)
  return response
}
export async function request<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
  const started = generation
  const response = await sessionFetch(path, init, authenticated)
  if (authenticated) assertCurrentSession(started)
  if (!response.ok) throw await failure(response)
  if (response.status === 204) return undefined as T
  const result: T = await response.json()
  if (authenticated) assertCurrentSession(started)
  return result
}
export async function logoutSession(): Promise<void> {
  // Cookie 跨标签共享，注销必须绑定本标签原始 access sid，不能刷新或匿名注销。
  const token = accessToken || pendingLogoutToken
  pendingLogoutToken = token
  clearSession()
  if (!token) return
  const started = generation
  await withSessionLock(async () => {
    assertCurrentSession(started)
    await fetchAuthConfig()
    assertCurrentSession(started)
    await request<void>('/api/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken, Authorization: 'Bearer ' + token }, body: '{}' }, false)
    if (pendingLogoutToken === token) pendingLogoutToken = ''
  })
}
