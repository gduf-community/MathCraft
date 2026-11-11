import { useCallback } from 'react'
import { fetchPlatformOverview } from '../../api/backend'
import { useOpsQuery } from './ops/useOpsQuery'

/** 原平台资源和成果批次统计，与运维运行统计分别加载。 */
export function LegacyOverview() {
  const load = useCallback((signal: AbortSignal) => fetchPlatformOverview(signal), [])
  const { data: overview, error, loading, refresh, lastSuccess } = useOpsQuery(load, true, 0)
  return <section className="space-y-4" aria-label="平台资源与历史批次">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold">平台资源与历史批次</h2>
        <p className="mt-1 text-sm text-ink-2">现有平台统计 · 真实数据</p>
      </div>
      <button type="button" onClick={refresh} disabled={loading}
        className="min-h-11 rounded-lg border border-line bg-white px-4 py-2 text-sm text-ink-2 transition-colors hover:bg-primary-light disabled:opacity-60">
        {loading ? '刷新中…' : '刷新平台统计'}
      </button>
    </div>
    {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
      平台统计刷新失败：{error} <button type="button" onClick={refresh} className="underline">重试</button>
    </p>}
    {lastSuccess && <p className="text-xs text-ink-2">最近成功更新：{new Date(lastSuccess).toLocaleString('zh-CN', { hour12: false })}</p>}
    {loading && !overview && <p role="status" className="rounded-xl bg-white p-5 text-sm text-ink-2">正在加载平台统计…</p>}

            <section className="grid gap-4 sm:grid-cols-3">
              <StatCard label="教师" value={overview ? (overview.accounts.teacher_active ?? 0) + (overview.accounts.teacher_disabled ?? 0) : '—'} />
              <StatCard label="学生" value={overview ? (overview.accounts.student_active ?? 0) + (overview.accounts.student_disabled ?? 0) : '—'} />
              <StatCard label="管理员" value={overview ? (overview.accounts.admin_active ?? 0) + (overview.accounts.admin_disabled ?? 0) : '—'} />
              <StatCard label="题库／知识库" value={overview?.resources.banks ?? '—'} />
              <StatCard label="文档" value={overview?.resources.documents ?? '—'} />
              <StatCard label="试卷" value={overview?.resources.papers ?? '—'} />
            </section>

            <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">平台信息</h2>
                  <p className="mt-1 text-sm text-ink-3">联系管理员：{overview?.admin_contact || '未配置'}</p>
                </div>
                <div className="text-sm text-ink-3">持久化生成批次总数：{overview?.task_total ?? '—'}</div>
              </div>
              <p className="mt-2 text-sm text-ink-3">状态统计覆盖全部持久化生成批次；下表仅展示最近 50 条，不包含仅存于任务缓存的运行中或失败任务。完成时间未记录。</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {overview && Object.entries(overview.task_status_counts).map(([status, count]) => (
                  <span key={status} className="rounded-full bg-page px-3 py-1 text-xs text-ink-2">{status}：{count}</span>
                ))}
              </div>
              {overview && overview.tasks.length > 0 && (
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-sm">
                    <thead className="border-b border-line text-ink-3">
                      <tr><th className="px-3 py-2">任务类型</th><th className="px-3 py-2">状态</th><th className="px-3 py-2">创建时间</th><th className="px-3 py-2">完成时间</th></tr>
                    </thead>
                    <tbody>
                      {overview.tasks.map((task) => (
                        <tr key={task.id} className="border-b border-line/70 last:border-0">
                          <td className="px-3 py-2">{task.type}</td>
                          <td className="px-3 py-2">{task.status}</td>
                          <td className="px-3 py-2 text-ink-3">{task.created_at}</td>
                          <td className="px-3 py-2 text-ink-3">{task.completed_at ?? '未记录'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>


  </section>
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return <div className="rounded-xl border border-line bg-white p-4 shadow-sm"><p className="text-sm text-ink-2">{label}</p><p className="mt-2 text-2xl font-semibold text-primary">{value}</p></div>
}
