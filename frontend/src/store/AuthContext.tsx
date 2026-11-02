/** 登录态上下文：持久化到 localStorage，刷新页面不掉线；主应用仅在登录后挂载 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { fetchAuthUser, login as authLogin } from '../api/auth'
import type { AuthRole, AuthUser } from '../api/auth'

const STORAGE_KEY = 'mathcraft-auth'

interface AuthContextValue {
  user: AuthUser | null
  /** 登录：校验账号密码并写入状态与本地存储 */
  login: (account: string, password: string, role: AuthRole) => Promise<AuthUser>
  /** 写入已通过校验的用户（供登录页先播离场动画再切换到主应用） */
  signIn: (user: AuthUser) => void
  /** 退出登录：清空状态与本地存储 */
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

function readStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const stored = JSON.parse(raw) as AuthUser
    if (!stored?.token || !stored?.role) return null
    return stored
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  // 初始挂载时按令牌恢复登录态（演示实现仅校验令牌格式）
  useEffect(() => {
    const stored = readStoredUser()
    if (!stored) return
    void fetchAuthUser(stored.token).then((fresh) => {
      if (fresh) setUser(fresh)
      else localStorage.removeItem(STORAGE_KEY)
    })
  }, [])

  const login = useCallback(async (account: string, password: string, role: AuthRole) => {
    const authUser = await authLogin(account, password, role)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(authUser))
    return authUser
  }, [])

  const signIn = useCallback((authUser: AuthUser) => {
    setUser(authUser)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(authUser))
  }, [])

  const logout = useCallback(() => {
    setUser(null)
    localStorage.removeItem(STORAGE_KEY)
  }, [])

  const value = useMemo(() => ({ user, login, signIn, logout }), [user, login, signIn, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
