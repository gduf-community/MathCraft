import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../../../api/session'

interface QueryState<T> {
  data: T | null
  loading: boolean
  error: string
  lastSuccess: string | null
}

/** 可取消的单飞只读查询；后台刷新保留旧结果，隐藏页面暂停轮询。 */
export function useOpsQuery<T>(
  load: (signal: AbortSignal) => Promise<T>, intervalMs = 15000,
) {
  const [state, setState] = useState<QueryState<T>>({
    data: null, loading: true, error: '', lastSuccess: null,
  })
  const runCurrent = useRef<() => void>(() => {})
  const refresh = useCallback(() => runCurrent.current(), [])
  useEffect(() => {
    let active = true
    let timer: number | undefined
    let controller: AbortController | undefined
    setState({ data: null, loading: true, error: '', lastSuccess: null })
    const schedule = () => {
      window.clearTimeout(timer)
      if (active && intervalMs > 0 && !document.hidden) {
        timer = window.setTimeout(() => void run(), intervalMs)
      }
    }
    async function run() {
      if (!active || controller) return
      window.clearTimeout(timer)
      const request = new AbortController()
      controller = request
      setState(previous => ({ ...previous, loading: true, error: '' }))
      try {
        const data = await load(request.signal)
        if (active && !request.signal.aborted) {
          setState({ data, loading: false, error: '', lastSuccess: new Date().toISOString() })
        }
      } catch (error: unknown) {
        if (active && !request.signal.aborted) {
          const denied = error instanceof ApiError && (error.status === 401 || error.status === 403)
          setState(previous => ({ ...previous, loading: false,
            data: denied ? null : previous.data, lastSuccess: denied ? null : previous.lastSuccess,
            error: error instanceof Error ? error.message : '数据暂不可用，请重试' }))
        }
      } finally {
        controller = undefined
        schedule()
      }
    }
    const visibilityChanged = () => {
      window.clearTimeout(timer)
      if (!document.hidden && intervalMs > 0) void run()
    }
    runCurrent.current = () => { void run() }
    void run()
    document.addEventListener('visibilitychange', visibilityChanged)
    return () => {
      active = false
      controller?.abort()
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', visibilityChanged)
      runCurrent.current = () => {}
    }
  }, [load, intervalMs])
  return { ...state, refresh }
}
