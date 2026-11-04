/** 启动时仅凭 HttpOnly Cookie 恢复，不信任任何旧持久化凭据。 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { fetchAuthUser, logout as authLogout } from '../api/auth'
import type { AuthUser } from '../api/auth'
import { ApiError, onSessionCleared, refreshSession } from '../api/session'
interface AuthContextValue { user: AuthUser | null; restoring: boolean; restoreError: string; restore: () => void; signIn: (user: AuthUser) => void; logout: () => Promise<void> }
const AuthContext = createContext<AuthContextValue | null>(null)
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [restoring, setRestoring] = useState(true)
  const [restoreError, setRestoreError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => onSessionCleared(() => setUser(null)), [])
  useEffect(() => {
    let active = true
    try { localStorage.removeItem('mathcraft-auth'); localStorage.removeItem('mc_token'); localStorage.removeItem('mathcraft-token') } catch { /* 存储被禁用不影响内存认证。 */ }
    void refreshSession().then(fetchAuthUser).then(fresh => { if (active) setUser(fresh) }).catch((error: unknown) => {
      if (active && !(error instanceof ApiError && error.status === 401)) setRestoreError('会话恢复失败，请重试或重新登录')
    }).finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [attempt])
  const restore = useCallback(() => { setRestoring(true); setRestoreError(''); setAttempt(n => n + 1) }, [])
  const signIn = useCallback((fresh: AuthUser) => { setUser(fresh); setRestoreError('') }, [])
  const logout = useCallback(async () => { await authLogout() }, [])
  const value = useMemo(() => ({ user, restoring, restoreError, restore, signIn, logout }), [user, restoring, restoreError, restore, signIn, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used within AuthProvider')
  return value
}
