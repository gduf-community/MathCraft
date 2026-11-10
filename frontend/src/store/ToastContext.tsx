import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { getSessionGeneration, onSessionCleared } from '../api/session'
import { useAuth } from './AuthContext'

export type ToastVariant = 'success' | 'error' | 'info'

export interface ToastMessage {
  id: number
  text: string
  variant: ToastVariant
}

interface ToastContextValue {
  toast: ToastMessage | null
  showToast: (text: string, variant?: ToastVariant) => void
  dismissToast: () => void
}

const ToastContext = createContext<ToastContextValue | null>(null)
const TOAST_DURATION = { success: 3000, error: 6000, info: 3000 } as const

/** 同一身份共享提示；会话失效立即清除，并拒绝旧请求的迟到反馈。 */
function SessionToastProvider({ children }: { children: ReactNode }) {
  const { authNotice, user } = useAuth()
  const [toast, setToast] = useState<ToastMessage | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const nextId = useRef(0)
  const mounted = useRef(true)
  const session = useRef(getSessionGeneration())
  const dismissToast = useCallback(() => {
    window.clearTimeout(timer.current)
    setToast(null)
  }, [])

  useEffect(() => {
    mounted.current = true
    const unsubscribe = onSessionCleared(dismissToast)
    return () => {
      mounted.current = false
      window.clearTimeout(timer.current)
      unsubscribe()
    }
  }, [dismissToast])

  const showToast = useCallback((text: string, variant: ToastVariant = 'info') => {
    if (!mounted.current || session.current !== getSessionGeneration()) return
    window.clearTimeout(timer.current)
    setToast({ id: ++nextId.current, text, variant })
    timer.current = window.setTimeout(dismissToast, TOAST_DURATION[variant])
  }, [dismissToast])

  // 安全操作确认成功后撤销会话，使用现有登录页通知在新匿名会话展示结果。
  useEffect(() => {
    if (!user && authNotice) showToast(authNotice, 'success')
  }, [authNotice, showToast, user])

  return <ToastContext.Provider value={{ toast, showToast, dismissToast }}>{children}</ToastContext.Provider>
}

/** 位于 AuthProvider 内、业务 AppProvider 外，管理员同样可使用。 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const identity = `${user?.userId ?? 'anonymous'}:${user?.role ?? ''}:${getSessionGeneration()}`
  return <SessionToastProvider key={identity}>{children}</SessionToastProvider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastContextValue {
  const value = useContext(ToastContext)
  if (!value) throw new Error('useToast must be used within ToastProvider')
  return value
}
