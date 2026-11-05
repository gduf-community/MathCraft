/** 认证 API：真实后端登录、当前用户、退出、两版改密。 */
import {
  changePasswordLoggedIn,
  fetchAuthConfig as backendFetchAuthConfig,
  changePasswordPublic,
  fetchAuthUser as backendFetchAuthUser,
  login as backendLogin,
  logout as backendLogout,
} from './backend'
import type { AuthRole, AuthUser } from './backend'

export type { AuthRole, AuthUser }
export type { AuthConfig } from './backend'

export async function fetchAuthConfig(): Promise<{ admin_contact: string }> {
  return backendFetchAuthConfig()
}
export async function login(account: string, password: string): Promise<AuthUser> {
  return backendLogin(account, password)
}

export async function fetchAuthUser(token: string): Promise<AuthUser | null> {
  return backendFetchAuthUser(token)
}

export async function logout(): Promise<void> {
  await backendLogout()
}

export async function changePassword(
  account: string,
  oldPassword: string,
  newPassword: string,
): Promise<void> {
  await changePasswordPublic(account, oldPassword, newPassword)
}

export async function changePasswordCurrent(oldPassword: string, newPassword: string): Promise<void> {
  await changePasswordLoggedIn(oldPassword, newPassword)
}
