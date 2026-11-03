/** 认证 API：真实后端登录、当前用户、退出、两版改密。 */
import {
  changePasswordLoggedIn,
  changePasswordPublic,
  fetchAuthUser as backendFetchAuthUser,
  login as backendLogin,
  logout as backendLogout,
} from './backend'
import type { AuthRole, AuthUser } from './backend'

export type { AuthRole, AuthUser }

export async function login(account: string, password: string, role: AuthRole): Promise<AuthUser> {
  return backendLogin(account, password, role)
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
  role: AuthRole,
): Promise<void> {
  await changePasswordPublic(account, oldPassword, newPassword, role)
}

export async function changePasswordCurrent(oldPassword: string, newPassword: string): Promise<void> {
  await changePasswordLoggedIn(oldPassword, newPassword)
}
