/** 用户认证契约；不提供邮箱密码或历史登录旁路。 */
import { mapAuthUser } from './backend'
import type { AuthRole, AuthUser } from './backend'
import { clearSession, establishSession, logoutSession, parseApiUser, request } from './session'
export { getAuthConfig, ApiError } from './session'
export type { AuthConfig } from './session'
export type { AuthRole, AuthUser }
export type CodePurpose = 'register' | 'login' | 'reset_password' | 'email_change_old' | 'email_change_new'
export interface EmailChallenge { challenge_id: string; expires_in: number; retry_after: number }
export interface EmailProof { email: string; challenge_id: string; code: string }
export interface Registration extends EmailProof { password: string; confirm_password: string; display_name: string; role: AuthRole; user_no: string | null }
async function authenticate(path: string, payload: unknown): Promise<AuthUser> {
  return establishSession(
    () => request<unknown>(path, { method: 'POST', body: JSON.stringify(payload) }, false),
    result => mapAuthUser(result.user, result.access_token),
  )
}
export const register = (payload: Registration) => authenticate('/api/auth/register', payload)
export const loginEmail = (payload: EmailProof & { role: AuthRole }) => authenticate('/api/auth/login/email', payload)
export const loginPassword = (user_no: string, password: string, role: AuthRole, turnstile_token: string) => authenticate('/api/auth/login/password', { user_no, password, role, turnstile_token })
export async function fetchAuthUser(): Promise<AuthUser> {
  const result = await request<unknown>('/api/auth/me')
  if (!result || typeof result !== 'object' || !('user' in result)) throw new Error('认证响应无效')
  return mapAuthUser(parseApiUser(result.user), '')
}
export function sendEmailCode(payload: { email: string; purpose: CodePurpose; turnstile_token: string; change_id?: string }) {
  return request<EmailChallenge>('/api/auth/email-code', { method: 'POST', body: JSON.stringify(payload) }, payload.purpose.startsWith('email_change'))
}
export async function resetPassword(payload: EmailProof & { new_password: string; confirm_password: string }) {
  await request<void>('/api/auth/password/reset', { method: 'POST', body: JSON.stringify(payload) }, false)
  clearSession()
}
export async function changePasswordCurrent(old_password: string, new_password: string, confirm_password: string) {
  await request<void>('/api/auth/password', { method: 'PUT', body: JSON.stringify({ old_password, new_password, confirm_password }) })
  clearSession()
}
export async function changeUserNo(user_no: string | null, current_password: string): Promise<AuthUser> {
  const user = await request<unknown>('/api/users/me/user-no', { method: 'PUT', body: JSON.stringify({ user_no, current_password }) })
  return mapAuthUser(parseApiUser(user), '')
}
export function startEmailChange(new_email: string) {
  return request<{ change_id: string; expires_in: number }>('/api/users/me/email-change', { method: 'POST', body: JSON.stringify({ new_email }) })
}
export async function changeEmail(payload: { change_id: string; old_challenge_id: string; old_code: string; new_challenge_id: string; new_code: string }) {
  await request<void>('/api/users/me/email', { method: 'PUT', body: JSON.stringify(payload) })
  clearSession()
}
export function developmentAccount(role: AuthRole) {
  return request<{ user_no: string; password: string }>('/api/auth/development-account?role=' + role, { method: 'POST', body: '{}', cache: 'no-store' }, false)
}
export const logout = logoutSession
export function validateNewPassword(password: string): string | undefined {
  if (Array.from(password).length < 8 || Array.from(password).length > 64 || new TextEncoder().encode(password).length > 72) return '密码须为 8–64 字符，UTF-8 不超过 72 字节'
}
