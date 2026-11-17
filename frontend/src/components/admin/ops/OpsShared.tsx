/* eslint-disable react-refresh/only-export-components -- 运行页面共用的格式化函数与展示组件。 */
import { useId, useState } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'
import { opsEntrypoints, opsStatuses } from '../../../types/ops'
import type { OpsFilters as Filters, OpsMeta, OpsWindow } from '../../../types/ops'

export const opsInputClass = 'min-h-11 min-w-0 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-primary'
export const opsButtonClass = 'inline-flex min-h-11 items-center justify-center rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink hover:bg-page focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50'
export const opsPrimaryClass = 'inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-4 py-2 text-sm text-white hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50'

/** 原生 dialog 负责背景 inert；完整 Tab 周期保持在对话框内。 */
export function trapOpsDialogFocus(event: KeyboardEvent<HTMLDialogElement>) {
  if (event.key !== 'Tab') return
  const element = event.currentTarget
  const focusable = Array.from(element.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )).filter(item => item.getClientRects().length > 0 && item.tabIndex >= 0)
  const first = focusable[0], last = focusable[focusable.length - 1]
  if (!first || !last) { event.preventDefault(); element.focus() }
  else if (event.shiftKey && (document.activeElement === first || document.activeElement === element)) {
    event.preventDefault(); last.focus()
  } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === element)) {
    event.preventDefault(); first.focus()
  }
}
const labels: Record<string, string> = {
  accepted: '已受理', running: '运行中', completed: '批次已保存', failed: '失败',
  canceled: '已取消', unknown: '未知', parameterized: '参数化出题', conversation: '对话出题',
  NEED_CONFIRM: '需要确认', MODEL_ERROR: '模型错误', RETRIEVAL_ERROR: '检索错误',
  GENERATION_ERROR: '生成错误', NO_PERSISTABLE_QUESTIONS: '没有可保存题目',
  PERSISTENCE_ERROR: '保存错误', TASK_SUBMISSION_ERROR: '任务提交错误',
  EXECUTION_ERROR: '执行错误', USER_CANCELED: '用户取消', EXECUTION_INTERRUPTED: '执行中断',
  OUTCOME_UNKNOWN: '结果不明', UNKNOWN: '错误分类未知',
}
export function opsLabel(value: string | null | undefined): string { return value ? labels[value] ?? '未知' : '未知' }
export function opsNumber(value: number | null | undefined): string {
  return value == null ? '未知' : value.toLocaleString('zh-CN')
}
export function opsTime(value: string | null | undefined): string {
  if (!value) return '未知'
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { hour12: false }) : '未知'
}
export function OpsBadge({ value }: { value: string | null }) {
  return <span className={`inline-block rounded-md border px-2 py-0.5 text-xs ${value === 'failed'
    ? 'border-danger/20 bg-danger/5 text-red-700' : 'border-line bg-page text-ink-2'}`}>{opsLabel(value)}</span>
}
export function OpsCard({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <section className="min-w-0 rounded-xl border border-line bg-white p-4 shadow-sm sm:p-5">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h3 className="min-w-0 break-words font-semibold text-ink [overflow-wrap:anywhere]">{title}</h3>{action}
    </div>{children}
  </section>
}
export function OpsFacts({ items }: { items: [string, ReactNode][] }) {
  return <dl className="grid gap-x-5 gap-y-3 text-sm sm:grid-cols-2">
    {items.map(([label, value]) => <div key={label} className="min-w-0">
      <dt className="text-ink-2">{label}</dt><dd className="mt-1 break-words text-ink [overflow-wrap:anywhere]">{value}</dd>
    </div>)}
  </dl>
}
export function OpsFeedback({ loading, error, hasData, empty, onRetry }: {
  loading: boolean; error: string; hasData: boolean; empty?: boolean; onRetry: () => void
}) {
  return <div aria-live="polite" className="space-y-2 text-sm">
    {loading && <p role="status" className="rounded-lg bg-primary-light p-3 text-ink-2">
      {hasData ? '正在刷新，暂时展示上次成功加载的数据…' : '正在加载运行数据…'}
    </p>}
    {error && <div role="alert" className="rounded-lg border border-danger/20 bg-danger/5 p-3 text-ink">
      <p>{hasData ? '刷新失败；以下为上次成功加载的旧数据。' : '无法加载运行数据。'}{error}</p>
      <button type="button" className={`${opsButtonClass} mt-2`} disabled={loading} onClick={onRetry}>重试查询</button>
    </div>}
    {!loading && !error && empty && <p className="rounded-lg border border-line bg-white p-6 text-center text-ink-2">
      当前筛选下没有匹配记录；仅覆盖已写入台账的运行。
    </p>}
  </div>
}
export function OpsMetaNotice({ meta, lastSuccess }: { meta: OpsMeta | null; lastSuccess?: string | null }) {
  return meta && <p className="text-xs text-ink-2">数据时间：{opsTime(meta.generated_at)}
    {lastSuccess && <> · 最近加载成功：{opsTime(lastSuccess)}</>} · 时间按本地时区显示</p>
}
export function OpsWindowNotice({ window }: { window: OpsWindow }) {
  return <p className="text-sm text-ink-2">受理时间窗口：{opsTime(window.from)} — {opsTime(window.to)}（包含开始，不包含结束）</p>
}
function localInput(value: string | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, -1)
}
const idFields = [
  ['owner_user_id', '归属账号 ID'], ['session_id', '会话 ID'], ['task_id', '任务 ID'], ['batch_id', '批次 ID'],
] as const

/** 草稿应用后才发查询；自定义时间转成带时区 ISO，不附加旧方案的时间上限。 */
export function OpsFilters({ query, onApply }: { query: Filters; onApply: (query: Filters) => void }) {
  const formId = useId()
  const [draft, setDraft] = useState({
    owner_user_id: query.owner_user_id ?? '', session_id: query.session_id ?? '',
    task_id: query.task_id ?? '', batch_id: query.batch_id ?? '',
    status: query.status ?? '', entrypoint: query.entrypoint ?? '',
  })
  const [range, setRange] = useState(query.from || query.to ? 'custom' : '24h')
  const [from, setFrom] = useState(localInput(query.from)), [to, setTo] = useState(localInput(query.to))
  const [error, setError] = useState('')
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const next: Filters = {}
    for (const [key] of idFields) {
      const value = draft[key].trim()
      if (value && !/^[A-Za-z0-9_.:-]{1,128}$/.test(value)) {
        setError('ID 须为 1–128 位英文字母、数字或 _ . : -。'); return
      }
      if (value) next[key] = value
    }
    next.status = opsStatuses.find(value => value === draft.status)
    next.entrypoint = opsEntrypoints.find(value => value === draft.entrypoint)
    if (range === 'custom') {
      const start = Date.parse(from), end = Date.parse(to)
      if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) {
        setError('请选择有效起止时间，开始须早于结束。'); return
      }
      next.from = new Date(start).toISOString(); next.to = new Date(end).toISOString()
    } else {
      const end = Date.now(), duration = range === '1h' ? 3_600_000 : range === '7d' ? 604_800_000 : 86_400_000
      next.from = new Date(end - duration).toISOString(); next.to = new Date(end).toISOString()
    }
    setError(''); onApply(next)
  }
  return <form onSubmit={apply} aria-label="运行筛选" className="space-y-3 rounded-xl border border-line bg-white p-4">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <label className="space-y-1 text-sm"><span>时间窗口</span>
        <select aria-label="时间窗口" className={opsInputClass} value={range} onChange={event => setRange(event.target.value)}>
          <option value="1h">近 1 小时</option><option value="24h">近 24 小时</option>
          <option value="7d">近 7 天</option><option value="custom">自定义</option>
        </select>
      </label>
      {range === 'custom' && <>
        <label className="space-y-1 text-sm"><span>开始时间（本地，包含）</span>
          <input type="datetime-local" step="0.001" className={opsInputClass} required value={from} onChange={event => setFrom(event.target.value)} />
        </label>
        <label className="space-y-1 text-sm"><span>结束时间（本地，不包含）</span>
          <input type="datetime-local" step="0.001" className={opsInputClass} required value={to} onChange={event => setTo(event.target.value)} />
        </label>
      </>}
      <label className="space-y-1 text-sm"><span>出题入口</span>
        <select aria-label="出题入口" className={opsInputClass} value={draft.entrypoint} onChange={event => {
          const value = event.target.value
          setDraft(previous => ({ ...previous, entrypoint: opsEntrypoints.find(item => item === value) ?? '' }))
        }}><option value="">全部</option>{opsEntrypoints.map(value => <option key={value} value={value}>{opsLabel(value)}</option>)}</select>
      </label>
      <label className="space-y-1 text-sm"><span>运行状态</span>
        <select aria-label="运行状态" className={opsInputClass} value={draft.status} onChange={event => {
          const value = event.target.value
          setDraft(previous => ({ ...previous, status: opsStatuses.find(item => item === value) ?? '' }))
        }}><option value="">全部</option>{opsStatuses.map(value => <option key={value} value={value}>{opsLabel(value)}</option>)}</select>
      </label>
      {idFields.map(([key, label]) => <label key={key} htmlFor={`${formId}-${key}`} className="space-y-1 text-sm">
        <span>{label}</span><input id={`${formId}-${key}`} className={opsInputClass} value={draft[key]} maxLength={128}
          autoComplete="off" placeholder="精确匹配" onChange={event => setDraft(previous => ({ ...previous, [key]: event.target.value }))} />
      </label>)}
    </div>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <div className="flex flex-wrap items-center gap-3">
      <button type="submit" className={opsPrimaryClass}>应用筛选</button>
      <button type="button" className={opsButtonClass} onClick={() => {
        setDraft({ owner_user_id: '', session_id: '', task_id: '', batch_id: '', status: '', entrypoint: '' })
        setRange('24h'); setFrom(''); setTo(''); setError(''); onApply({})
      }}>重置查询</button>
      <span className="text-xs text-ink-2">精确匹配并取交集；应用后返回第一页。时间窗口按应用时刻确定。</span>
    </div>
  </form>
}
