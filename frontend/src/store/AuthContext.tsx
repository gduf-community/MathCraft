/** 登录态上下文：真实 token 持久化到 localStorage，刷新后调 /api/auth/me 恢复。 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { fetchAuthUser, login as authLogin, logout as authLogout } from '../api/auth'
import type { AuthRole, AuthUser } from '../api/auth'
import { setApiToken } from '../api/backend'

const STORAGE_KEY = 'mathcraft-auth'

interface AuthContextValue {
  user: AuthUser | null
  login: (account: string, password: string, role: AuthRole) => Promise<AuthUser>
  signIn: (user: AuthUser) => void
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
  useEffect(() => {
    const stored = readStoredUser()
    if (!stored) return
    setApiToken(stored.token)
    void fetchAuthUser(stored.token).then((fresh) => {
      if (fresh) setUser(fresh)
      else {
        localStorage.removeItem(STORAGE_KEY)
        setApiToken(null)
      }
    })
  }, [])

  const login = useCallback(async (account: string, password: string, role: AuthRole) => {
    const authUser = await authLogin(account, password, role)
    setApiToken(authUser.token)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(authUser))
    return authUser
  }, [])

  const signIn = useCallback((authUser: AuthUser) => {
    setApiToken(authUser.token)
    setUser(authUser)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(authUser))
  }, [])

  const logout = useCallback(() => {
    void authLogout()
    setApiToken(null)
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
