import { useCallback, useEffect, useRef, useState } from 'react'

interface QueryState<T> {
  data: T | null
  loading: boolean
  mutating: boolean
  error: string
  lastSuccess: string | null
}

type QueryMutation<T> = (
  action: (signal: AbortSignal) => Promise<void>,
  update: (data: T) => T,
) => Promise<boolean>

/** 可取消的单飞查询；后台刷新保留结果，页面隐藏时停止定时查询。 */
export function useOpsQuery<T>(
  load: (signal: AbortSignal) => Promise<T>,
  enabled = true,
  intervalMs = 15000,
) {
  const [state, setState] = useState<QueryState<T>>({
    data: null, loading: enabled, mutating: false, error: '', lastSuccess: null,
  })
  const runCurrent = useRef<() => void>(() => {})
  const refresh = useCallback(() => runCurrent.current(), [])
  const mutateCurrent = useRef<QueryMutation<T> | null>(null)
  const mutate = useCallback<QueryMutation<T>>(async (action, update) => {
    const current = mutateCurrent.current
    return current ? current(action, update) : false
  }, [])

  useEffect(() => {
    let active = true
    let refreshQueued = false
    let timer: number | undefined
    let controller: AbortController | undefined
    let writeController: AbortController | undefined
    setState({ data: null, loading: enabled, mutating: false, error: '', lastSuccess: null })

    const schedule = () => {
      window.clearTimeout(timer)
      if (active && enabled && !writeController && intervalMs > 0 && !document.hidden) {
        timer = window.setTimeout(() => void run(), intervalMs)
      }
    }
    async function run() {
      if (!active || !enabled || controller || writeController) return
      window.clearTimeout(timer)
      const request = new AbortController()
      controller = request
      const signal = request.signal
      setState(previous => ({ ...previous, loading: true, error: '' }))
      try {
        const data = await load(signal)
        if (active && !signal.aborted) {
          setState({ data, loading: false, mutating: false, error: '', lastSuccess: new Date().toISOString() })
        }
      } catch (error: unknown) {
        if (active && !signal.aborted) {
          setState(previous => ({ ...previous, loading: false,
            error: error instanceof Error ? error.message : '数据暂不可用，请重试' }))
        }
      } finally {
        // 写操作可撤销并替换当前查询；旧请求即使忽略 abort 也不能干扰新请求。
        if (controller === request) {
          controller = undefined
          if (active && refreshQueued) {
            refreshQueued = false
            void run()
          } else schedule()
        }
      }
    }
    mutateCurrent.current = async (action, update) => {
      if (!active || !enabled || writeController) return false
      const request = new AbortController()
      writeController = request
      controller?.abort()
      controller = undefined
      window.clearTimeout(timer)
      setState(previous => ({ ...previous, loading: false, mutating: true }))
      try {
        await action(request.signal)
        if (!active || request.signal.aborted) return false
        setState(previous => ({ ...previous,
          data: previous.data === null ? null : update(previous.data) }))
        return true
      } catch (error: unknown) {
        if (!active || request.signal.aborted) return false
        throw error
      } finally {
        if (writeController === request) {
          writeController = undefined
          if (active) {
            setState(previous => ({ ...previous, mutating: false }))
            refreshQueued = false
            void run()
          }
        }
      }
    }
    const visibilityChanged = () => {
      window.clearTimeout(timer)
      if (!document.hidden) void run()
    }
    runCurrent.current = () => {
      if (controller || writeController) refreshQueued = true
      else void run()
    }
    if (enabled) {
      void run()
      document.addEventListener('visibilitychange', visibilityChanged)
    }
    return () => {
      active = false
      controller?.abort()
      writeController?.abort()
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', visibilityChanged)
      runCurrent.current = () => {}
      mutateCurrent.current = null
    }
  }, [load, enabled, intervalMs])

  return { ...state, refresh, mutate }
}
