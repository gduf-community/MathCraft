import { useCallback, useEffect, useRef, useState } from 'react'

interface QueryState<T> {
  data: T | null
  loading: boolean
  error: string
  lastSuccess: string | null
}

/** 可取消的单飞查询；后台刷新保留结果，页面隐藏时停止定时查询。 */
export function useOpsQuery<T>(
  load: (signal: AbortSignal) => Promise<T>,
  enabled = true,
  intervalMs = 15000,
) {
  const [state, setState] = useState<QueryState<T>>({
    data: null, loading: enabled, error: '', lastSuccess: null,
  })
  const runCurrent = useRef<() => void>(() => {})
  const refresh = useCallback(() => runCurrent.current(), [])

  useEffect(() => {
    let active = true
    let inFlight = false
    let refreshQueued = false
    let timer: number | undefined
    let controller: AbortController | undefined
    setState({ data: null, loading: enabled, error: '', lastSuccess: null })

    const schedule = () => {
      window.clearTimeout(timer)
      if (active && enabled && intervalMs > 0 && !document.hidden) {
        timer = window.setTimeout(() => void run(), intervalMs)
      }
    }
    async function run() {
      if (!active || !enabled || inFlight) return
      window.clearTimeout(timer)
      controller = new AbortController()
      const signal = controller.signal
      inFlight = true
      setState(previous => ({ ...previous, loading: true, error: '' }))
      try {
        const data = await load(signal)
        if (active && !signal.aborted) {
          setState({ data, loading: false, error: '', lastSuccess: new Date().toISOString() })
        }
      } catch (error: unknown) {
        if (active && !signal.aborted) {
          setState(previous => ({ ...previous, loading: false,
            error: error instanceof Error ? error.message : '数据暂不可用，请重试' }))
        }
      } finally {
        inFlight = false
        if (active && refreshQueued) {
          refreshQueued = false
          void run()
        } else schedule()
      }
    }
    const visibilityChanged = () => {
      window.clearTimeout(timer)
      if (!document.hidden) void run()
    }
    runCurrent.current = () => {
      if (inFlight) refreshQueued = true
      else void run()
    }
    if (enabled) {
      void run()
      document.addEventListener('visibilitychange', visibilityChanged)
    }
    return () => {
      active = false
      controller?.abort()
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', visibilityChanged)
      runCurrent.current = () => {}
    }
  }, [load, enabled, intervalMs])

  return { ...state, refresh }
}
