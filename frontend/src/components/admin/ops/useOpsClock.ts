import { useEffect, useRef, useState } from 'react'

/** 使用服务端快照时钟和页面经过时间，避免本机时钟偏差或失败轮询延长证据寿命。 */
export function useOpsClock(generatedAt: string): number {
  const baseline = useRef({ serverTime: Date.parse(generatedAt), wallTime: Date.now(), monotonicTime: performance.now() })
  const [now, setNow] = useState(Date.parse(generatedAt))
  useEffect(() => {
    const tick = () => {
      const nextWall = Date.now()
      const nextMonotonic = performance.now()
      // 单调时钟抵抗校时回拨，墙钟增量补足 Windows 休眠；已过期证据不能倒退恢复。
      const elapsed = Math.max(0, nextWall - baseline.current.wallTime, nextMonotonic - baseline.current.monotonicTime)
      baseline.current.serverTime += elapsed
      baseline.current.wallTime = nextWall
      baseline.current.monotonicTime = nextMonotonic
      setNow(baseline.current.serverTime)
    }
    const timer = window.setInterval(tick, 1000)
    document.addEventListener('visibilitychange', tick)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [])
  useEffect(() => {
    const serverTime = Date.parse(generatedAt)
    if (!Number.isFinite(serverTime)) return
    // 筛选请求暂时清空数据或重读旧快照时，不回拨已经走过的服务端时间。
    baseline.current.serverTime = Number.isFinite(baseline.current.serverTime)
      ? Math.max(baseline.current.serverTime, serverTime) : serverTime
    setNow(baseline.current.serverTime)
  }, [generatedAt])
  const snapshotTime = Date.parse(generatedAt)
  return Number.isFinite(now) && Number.isFinite(snapshotTime) ? Math.max(now, snapshotTime)
    : Number.isFinite(now) ? now : snapshotTime
}
