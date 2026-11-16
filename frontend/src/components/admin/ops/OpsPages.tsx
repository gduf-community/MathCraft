import { useCallback, useRef, useState } from 'react'
import { opsStatuses } from '../../../types/ops'
import type { OpsClient, OpsFilters as Filters, OpsRun, OpsWindow } from '../../../types/ops'
import {
  OpsBadge, OpsCard, OpsFacts, OpsFeedback, OpsFilters, OpsMetaNotice, OpsWindowNotice,
  opsButtonClass, opsInputClass, opsLabel, opsNumber, opsPrimaryClass, opsTime,
} from './OpsShared'
import { useOpsQuery } from './useOpsQuery'

/** 概览和列表展示相同运行摘要，不读取题目或当前题量来重算历史。 */
function RunCards({ runs, onOpenRun }: { runs: OpsRun[]; onOpenRun: (id: string) => void }) {
  return <div className="space-y-3">{runs.map(run => <OpsCard key={run.run_id} title={run.run_id}
    action={<button type="button" className={opsPrimaryClass} onClick={() => onOpenRun(run.run_id)}
      aria-label={`查看运行 ${run.run_id}`}>查看详情</button>}>
    <div className="mb-3"><OpsBadge value={run.status} /></div>
    <OpsFacts items={[
      ['归属账号', run.owner_user_id], ['入口', opsLabel(run.entrypoint)],
      ['请求数量', opsNumber(run.requested_count)], ['已保存数量', opsNumber(run.delivered_count)],
      ['受理时间', opsTime(run.accepted_at)], ['最后观测时间', opsTime(run.last_observed_at)],
      ['会话 ID', run.session_id ?? '未知／不适用'], ['任务 ID', run.task_id ?? '未知／不适用'],
      ['批次 ID', run.batch_id ?? '尚未确认'],
      ['错误分类', run.error_code ? `${opsLabel(run.error_code)}（${run.error_code}）` : '无错误分类'],
    ]} />
  </OpsCard>)}</div>
}
export function OpsOverviewPanel({ client, onOpenRuns, onOpenRun }: {
  client: OpsClient; onOpenRuns: (query?: Filters) => void; onOpenRun: (id: string) => void
}) {
  const [query, setQuery] = useState<Filters>({})
  const load = useCallback((signal: AbortSignal) => client.getOverview(query, signal), [client, query])
  const result = useOpsQuery(load)
  const data = result.data
  const cohort: Filters = data ? { ...query, from: data.window.from, to: data.window.to } : query
  return <section className="space-y-4" aria-label="出题运行概览">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-xl font-semibold">出题运行概览</h2>
        <p className="mt-1 text-sm text-ink-2">仅统计已记录运行；批次已保存不表示题量达标或数学质量通过。</p></div>
      <button type="button" className={opsButtonClass} disabled={result.loading} onClick={result.refresh}>刷新概览</button>
    </div>
    <OpsFilters key={JSON.stringify(query)} query={query} onApply={setQuery} />
    <OpsFeedback {...result} hasData={!!data} empty={data?.total_runs === 0} onRetry={result.refresh} />
    <OpsMetaNotice meta={data} lastSuccess={result.lastSuccess} />
    {data && <>
      <OpsWindowNotice window={data.window} />
      <OpsCard title="窗口内运行" action={<button type="button" className={opsButtonClass}
        onClick={() => onOpenRuns(cohort)}>查看全部运行</button>}>
        <p className="mb-4 text-sm">已记录总数：<strong>{opsNumber(data.total_runs)}</strong></p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">{opsStatuses.map(status => <button
          type="button" key={status} className="min-h-11 rounded-lg bg-page p-3 text-left hover:bg-primary-light focus-visible:outline-2 focus-visible:outline-primary"
          onClick={() => onOpenRuns({ ...cohort, status })}>
          <span className="block text-sm text-ink-2">{opsLabel(status)}</span>
          <span className="mt-1 block text-xl font-semibold">{opsNumber(data.status_counts[status])}</span>
        </button>)}</div>
        <p className="mt-3 text-xs text-ink-2">未知单独计数；记录总数不代表历史采集完整。每 15 秒刷新，页面隐藏时暂停。</p>
      </OpsCard>
      <h3 className="font-semibold">最近运行（最多 10 条）</h3>
      <RunCards runs={data.recent_runs} onOpenRun={onOpenRun} />
    </>}
  </section>
}
interface RunsProps { client: OpsClient; initialQuery?: Filters; onOpenRun: (id: string) => void }
export function RunsPanel({ client, initialQuery, onOpenRun }: RunsProps) {
  const [query, setQuery] = useState<Filters>(initialQuery ?? {})
  const [limit, setLimit] = useState(20), [offset, setOffset] = useState(0)
  const [paging, setPaging] = useState(false)
  const anchor = useRef<OpsWindow | null>(null)
  const load = useCallback(async (signal: AbortSignal) => {
    const window = paging ? anchor.current : null
    const result = await client.listRuns({ ...query,
      ...(window ? { from: window.from, to: window.to } : {}), limit, offset }, signal)
    if (!signal.aborted) anchor.current = result.window
    return result
  }, [client, query, limit, offset, paging])
  const result = useOpsQuery(load, paging ? 0 : 15000)
  const data = result.data
  const apply = (next: Filters) => { anchor.current = null; setPaging(false); setOffset(0); setQuery(next) }
  const refresh = () => { if (paging) { setPaging(false); setOffset(0) } else result.refresh() }
  return <section className="space-y-4" aria-label="出题运行列表">
    <div><h2 className="text-xl font-semibold">出题运行</h2>
      <p className="mt-1 text-sm text-ink-2">按受理时间倒序查询。未知保持未知；最后观测时间不表示心跳。</p></div>
    <OpsFilters key={JSON.stringify(query)} query={query} onApply={apply} />
    <div className="flex flex-wrap items-end gap-3">
      <label className="text-sm"><span>每页数量</span><select aria-label="每页数量" className={opsInputClass} value={limit}
        onChange={event => { setPaging(false); setOffset(0); setLimit(Number(event.target.value)) }}>
        {[20, 50, 100].map(value => <option key={value} value={value}>{value}</option>)}
      </select></label>
      <button type="button" className={opsButtonClass} disabled={result.loading} onClick={refresh}>刷新第一页</button>
    </div>
    <OpsFeedback {...result} hasData={!!data} empty={data?.items.length === 0} onRetry={result.refresh} />
    <OpsMetaNotice meta={data} lastSuccess={result.lastSuccess} />
    {data && <OpsWindowNotice window={data.window} />}
    {data && <RunCards runs={data.items} onOpenRun={onOpenRun} />}
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-white p-4">
      <div className="text-sm text-ink-2">
        <p>第 {Math.floor(offset / limit) + 1} 页 · 每页 {limit} 条{data && ` · 本页 ${data.items.length} 条`}</p>
        <p>{paging ? '翻页后暂停自动刷新；刷新回到第一页。' : '首页每 15 秒刷新；页面隐藏时暂停。'}</p>
        <p className="mt-1 text-xs">翻页沿用同一时间窗口；新增运行或状态变化仍可能移动页边界。</p>
      </div>
      <div className="flex gap-2">
        <button type="button" className={opsButtonClass} disabled={result.loading || offset === 0}
          onClick={() => { setPaging(true); setOffset(value => Math.max(0, value - limit)) }}>上一页</button>
        <button type="button" className={opsPrimaryClass} disabled={result.loading || !data?.page.has_more || offset > 2_147_483_647 - limit}
          onClick={() => { setPaging(true); setOffset(value => value + limit) }}>下一页</button>
      </div>
    </div>
  </section>
}
