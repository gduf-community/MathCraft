const DAY = 86_400_000

/** 收藏时间距今天数，向下取整 */
export function daysAgo(iso: string): number {
  const time = new Date(iso).getTime()
  if (Number.isNaN(time)) return 0
  return Math.max(0, Math.floor((Date.now() - time) / DAY))
}

/** 「今天 / 昨天 / N 天前 / N 个月前」 */
export function formatCollectedAt(iso: string): string {
  const days = daysAgo(iso)
  if (days <= 0) return '今天'
  if (days === 1) return '昨天'
  if (days <= 30) return `${days} 天前`
  return `${Math.round(days / 30)} 个月前`
}

/** 本周新增：最近 7 天内收藏 */
export function isWithinWeek(iso: string): boolean {
  return daysAgo(iso) <= 7
}
