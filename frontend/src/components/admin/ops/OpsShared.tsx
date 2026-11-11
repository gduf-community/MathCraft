/* eslint-disable react-refresh/only-export-components -- 运维页面共用的纯格式化函数与展示组件。 */
import { useId, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import type { OpsMeta, OpsQuery, OpsRun } from '../../../types/ops'

export const opsInputClass = 'min-h-11 min-w-0 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink transition-colors focus-visible:outline-2 focus-visible:outline-primary'
export const opsButtonClass = 'inline-flex min-h-11 items-center justify-center rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink transition-colors hover:bg-page focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50'
export const opsPrimaryClass = 'inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-4 py-2 text-sm text-white transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50'

const labels: Record<string, string> = {
  accepted: '已受理', running: '运行中', completed: '正常结束', failed: '失败',
  cancelled: '已取消', unknown: '未知', met: '规则达标', attention: '需关注',
  not_evaluated: '未评估', complete: '完整', partial: '部分缺失', not_collected: '未采集',
  healthy: '可用', degraded: '降级', unavailable: '不可用', firing: '告警中',
  resolved: '轮次已关闭', active: '条件成立', clear: '条件已解除', warning: '警告', critical: '严重',
  parameterized: '参数化出题', conversation: '对话出题', platform: '平台', account: '账号', run: '运行',
  personal: '个人凭据', none: '无', passive: '实际调用', probe: '受控探测', mixed: '混合证据',
  model: '模型', embedding: '嵌入', reranker: '重排', redis: 'Redis',
  vector_store: '向量库', database: '数据库', phoenix: 'Phoenix',
  queued: '等待开始', preparing: '准备', retrieval: '检索', generation: '生成',
  review: '审核', repair: '修补', persisting: '持久化', finalizing: '收尾',
  skipped: '已跳过', not_required: '不要求审核', shortfall: '题量不足',
  waiting_suspected: '疑似等待过久', long_running_suspected: '疑似长时间运行', heartbeat_stale: '心跳陈旧',
  dependency_failure: '依赖连续失败', run_failure: '运行失败事件', quality_attention: '交付质量关注',
  available: '可查看', pending: '等待中', expired: '已过保留期', not_found: '查无追踪',
  forbidden: '无查看权限', not_started: '未开始导出', submitted: '导出端已受理', dropped: '导出已丢弃',
  no_samples: '无有效样本', incomplete: '证据不完整', empty_output: '无交付题目',
  success: '成功', unconfigured: '未配置阈值', trigger: '触发', reminder: '持续提醒', recovery: '恢复',
  QUANTITY_SHORTFALL: '最终交付题量不足', REVIEW_SKIPPED: '应审题目被跳过',
  REVIEW_FAILED: '审核未通过仍交付', DEGRADED: '存在降级', RETRIEVAL_FALLBACK: '检索使用替代路径',
  REVIEW_UNAVAILABLE: '审核不可用', UNREVIEWED_RELEASE: '未经明确审核放行', MODEL_FALLBACK: '模型使用替代路径',
  MODEL_CALL_FAILED: '模型调用失败', TOOL_FAILED: '工具执行失败', DEPENDENCY_FAILED: '依赖失败',
  PERSIST_FAILED: '成果持久化失败', USER_CANCELLED: '用户取消', INTERNAL_ERROR: '内部错误', UNKNOWN: '原因未知',
  AUTH_INVALID: '凭据无效', QUOTA_EXHAUSTED: '额度耗尽', TIMEOUT: '请求超时',
  CONNECTION_FAILED: '连接失败', SERVICE_ERROR: '服务错误', OBSERVER_STALE: '监测器评估已陈旧',
  WAITING_FOR_EXPORT: '等待导出', LOOKUP_UNAVAILABLE: '追踪查询通道不可用',
  RETENTION_ELAPSED: '已超过详细追踪保留期', ACCESS_UNVERIFIED: '尚未核验查看权限',
  MAPPING_UNCONFIRMED: '追踪映射尚未确认', RECOVERED: '已有恢复证据',
  RUN_TERMINATED: '运行已终止', HEARTBEAT_RESUMED: '心跳恢复', BELOW_THRESHOLD: '持续低于阈值',
  ACTIVE_RUN: '活动运行保留', ACTIVE_FAULT: '活动故障保留', DETECTION_PENDING: '待继续检测',
  OPS_DATA_UNAVAILABLE: '运维摘要暂不可用', OPS_RUN_NOT_FOUND: '运行摘要不存在或已过保留期',
  OPS_NOT_READY: '运维采集尚未就绪', FORBIDDEN: '需要管理员权限', TOKEN_EXPIRED: '登录已失效',
  NOT_COLLECTED: '未采集到有效证据', LOOKUP_FAILED: '单条追踪核验失败',
  EXPORT_FAILED: '追踪导出失败', EXPORT_DROPPED: '追踪导出已丢弃',
  EXPORT_PENDING: '追踪仍在等待导出', TRACE_NOT_FOUND: '按映射查询未找到追踪',
  TRACE_INCOMPLETE: '追踪记录不完整', ACCESS_DENIED: '查看权限被拒绝',
  EVIDENCE_STALE: '单条证据已陈旧', COLLECTOR_UNAVAILABLE: '采集器不可用',
  VALIDATION_ERROR: '查询参数无效，请检查时间范围或刷新第一页',
}

export function opsLabel(value: string | null | undefined): string {
  if (value == null || value === '') return '未知'
  return labels[value] ?? `未识别状态（${value}）`
}

export function opsNumber(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value)
    ? '未知' : value.toLocaleString('zh-CN', { maximumFractionDigits: 20 })
}

export function opsPercent(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '未知' : `${(value * 100).toFixed(1)}%`
}

export function opsTime(value: string | null | undefined): string {
  if (!value) return '未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '未知' : date.toLocaleString('zh-CN', { hour12: false })
}

export function opsDuration(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '未知'
  if (value < 1000) return `${value.toLocaleString('zh-CN')} 毫秒`
  if (value < 60_000) return `${(value / 1000).toFixed(1)} 秒`
  return `${(value / 60_000).toFixed(1)} 分钟`
}

export function OpsBadge({ value }: { value: string | null | undefined }) {
  const problem = ['failed', 'unavailable', 'critical', 'attention', 'firing', 'shortfall'].includes(value ?? '')
  return (
    <span className={`inline-block rounded-md border px-2 py-0.5 text-xs ${problem
      ? 'border-danger/20 bg-danger/5 text-red-700'
      : 'border-line bg-page text-ink-2'}`}>
      {opsLabel(value)}
    </span>
  )
}

export function OpsReasons({ codes }: { codes: string[] | null | undefined }) {
  if (codes == null) return <span className="text-sm text-ink-2">原因未知／未采集</span>
  if (!codes.length) return <span className="text-sm text-ink-2">已确认无此类标记</span>
  return <ul className="flex flex-wrap gap-2">{codes.map(code => (
    <li key={code} className="rounded-md bg-page px-2 py-1 text-xs text-ink">
      {opsLabel(code)} <span className="break-all text-ink-2">{code}</span>
    </li>
  ))}</ul>
}

export function OpsCard({ title, children, action }: {
  title: string; children: ReactNode; action?: ReactNode
}) {
  return <section className="min-w-0 rounded-xl border border-line bg-white p-4 shadow-sm sm:p-5">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h3 className="min-w-0 break-words font-semibold text-ink [overflow-wrap:anywhere]">{title}</h3>{action}
    </div>
    {children}
  </section>
}

export function OpsFacts({ items }: { items: [string, ReactNode][] }) {
  return <dl className="grid gap-x-5 gap-y-3 text-sm sm:grid-cols-2">
    {items.map(([label, value]) => <div key={label} className="min-w-0">
      <dt className="text-ink-2">{label}</dt>
      <dd className="mt-1 break-words text-ink [overflow-wrap:anywhere]">{value}</dd>
    </div>)}
  </dl>
}

export function OpsFeedback({ loading, error, hasData, empty, emptyText, onRetry }: {
  loading: boolean; error: string; hasData: boolean; empty?: boolean;
  emptyText?: string; onRetry: () => void
}) {
  return <div aria-live="polite" className="space-y-2 text-sm">
    {loading && <p role="status" className="rounded-lg bg-primary-light p-3 text-ink-2">
      {hasData ? '正在刷新，暂时展示上次成功加载的数据…' : '正在加载运维摘要…'}
    </p>}
    {error && <div role="alert" className="rounded-lg border border-danger/20 bg-danger/5 p-3 text-ink">
      <p>{hasData ? '刷新失败；以下为已加载的旧数据。' : '无法加载运维数据。'}{error}</p>
      <button type="button" className={`${opsButtonClass} mt-2`} onClick={onRetry}>重新加载第一页</button>
    </div>}
    {!loading && !error && empty && <p className="rounded-lg border border-line bg-white p-6 text-center text-ink-2">
      {emptyText ?? '当前筛选下没有匹配记录；空列表不代表采集完整或没有故障。'}
    </p>}
  </div>
}

export function OpsMetaNotice({ meta, lastSuccess }: {
  meta: OpsMeta | null; lastSuccess?: string | null
}) {
  if (!meta) return null
  return <div className="space-y-2 text-sm">
    <p className="text-ink-2">服务端生成：{opsTime(meta.generated_at)}
      {lastSuccess && <> · 最近加载成功：{opsTime(lastSuccess)}</>} · 时间均为本地时区</p>
    {meta.data_state === 'partial' && <p role="status" className="rounded-lg border border-star/30 bg-star/5 p-3 text-ink">
      摘要存在采集缺口（partial），已知样本不能代表全部请求，未知值未计为零。
    </p>}
    {meta.warnings.length > 0 && <ul className="space-y-1 rounded-lg border border-star/30 bg-star/5 p-3 text-ink">
      {meta.warnings.map((warning, index) => <li key={`${warning.code}:${index}`}>
        {warning.message} <span className="break-all text-ink-2">（{warning.code}）</span>
      </li>)}
    </ul>}
  </div>
}

export function OpsRunStates({ run }: { run: OpsRun }) {
  return <dl className="grid grid-cols-3 gap-3 text-sm">
    <div><dt className="mb-1 text-ink-2">执行</dt><dd><OpsBadge value={run.execution_status} /></dd></div>
    <div><dt className="mb-1 text-ink-2">交付质量</dt><dd><OpsBadge value={run.quality.status} /></dd></div>
    <div><dt className="mb-1 text-ink-2">详细追踪</dt><dd><OpsBadge value={run.trace.availability} /></dd></div>
  </dl>
}

export interface OpsFilterField {
  name: string
  label: string
  options?: readonly string[]
}

function localInput(value: string | number | undefined): string {
  if (typeof value !== 'string') return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return shifted.toISOString().slice(0, 16)
}

/** 应用筛选时才转 UTC；告警精确定位默认不附带时间窗。 */
export function OpsFilters({ fields, query, onApply, timeWindow = true, children }: {
  fields: readonly OpsFilterField[]; query: OpsQuery; onApply: (query: OpsQuery) => void;
  timeWindow?: boolean; children?: ReactNode
}) {
  const id = useId()
  const [draft, setDraft] = useState<OpsQuery>(query)
  const [range, setRange] = useState(query.from || query.to ? 'custom' : query.alert_id ? 'retained' : '24h')
  const [from, setFrom] = useState(localInput(query.from))
  const [to, setTo] = useState(localInput(query.to))
  const [error, setError] = useState('')

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const next: OpsQuery = {}
    for (const field of fields) {
      const value = String(draft[field.name] ?? '').trim()
      if (value) next[field.name] = value
    }
    if ((next.scope === 'account') && !next.owner_user_id) {
      setError('账号范围必须填写账号 ID。')
      return
    }
    if (next.scope === 'platform' && next.owner_user_id) {
      setError('平台范围不能同时筛选个人账号，请切换为账号范围。')
      return
    }
    if (timeWindow && range === 'retained' && !next.alert_id) {
      setError('整个保留期仅用于按告警 ID 精确定位，请填写告警 ID 或选择时间窗口。')
      return
    }
    if (timeWindow && range === 'custom') {
      const start = new Date(from).getTime()
      const end = new Date(to).getTime()
      const now = Date.now()
      if (!from || !to || !Number.isFinite(start) || !Number.isFinite(end)
        || start >= end || end > now || end - start > 14 * 86_400_000) {
        setError('请选择有效起止时间：开始早于结束，跨度不超过 14 天，且不能在未来。')
        return
      }
      next.from = new Date(start).toISOString()
      next.to = new Date(end).toISOString()
    } else if (timeWindow && range !== 'retained') {
      const now = Date.now()
      const duration = range === '1h' ? 3_600_000 : range === '24h' ? 86_400_000 : 7 * 86_400_000
      next.from = new Date(now - duration).toISOString()
      next.to = new Date(now).toISOString()
    }
    setError('')
    onApply(next)
  }

  return <form onSubmit={apply} className="space-y-3 rounded-xl border border-line bg-white p-4">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {timeWindow && <label className="space-y-1 text-sm text-ink" htmlFor={`${id}-range`}>
        <span>时间窗口</span>
        <select id={`${id}-range`} className={opsInputClass} value={range} onChange={event => setRange(event.target.value)}>
          <option value="1h">近 1 小时</option><option value="24h">近 24 小时</option>
          <option value="7d">近 7 天</option><option value="custom">自定义（最多 14 天）</option>
          {fields.some(field => field.name === 'alert_id') && <option value="retained">告警 ID：整个保留期</option>}
        </select>
      </label>}
      {timeWindow && range === 'custom' && <>
        <label className="space-y-1 text-sm text-ink"><span>开始时间（本地，包含）</span>
          <input type="datetime-local" className={opsInputClass} required value={from} onChange={event => setFrom(event.target.value)} />
        </label>
        <label className="space-y-1 text-sm text-ink"><span>结束时间（本地，不包含）</span>
          <input type="datetime-local" className={opsInputClass} required value={to} onChange={event => setTo(event.target.value)} />
        </label>
      </>}
      {fields.map(field => <label key={field.name} className="space-y-1 text-sm text-ink" htmlFor={`${id}-${field.name}`}>
        <span>{field.label}</span>
        {field.options ? <select id={`${id}-${field.name}`} value={draft[field.name] ?? ''} className={opsInputClass}
          onChange={event => {
            const value = event.target.value
            setDraft(previous => ({ ...previous, [field.name]: value }))
          }}>
          <option value="">全部</option>
          {field.options.map(value => <option key={value} value={value}>{opsLabel(value)}</option>)}
        </select> : <input id={`${id}-${field.name}`} value={draft[field.name] ?? ''} className={opsInputClass}
          autoComplete="off" placeholder="精确匹配"
          onChange={event => {
            const value = event.target.value
            setDraft(previous => ({ ...previous, [field.name]: value }))
            if (field.name === 'alert_id' && value.trim() && range !== 'custom') setRange('retained')
          }} />}
      </label>)}
    </div>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <div className="flex flex-wrap items-center gap-3">
      <button type="submit" className={opsPrimaryClass}>应用筛选</button>
      <button type="button" className={opsButtonClass} onClick={() => {
        setDraft({}); setRange('24h'); setFrom(''); setTo(''); setError(''); onApply({})
      }}>重置查询</button>
      <span className="text-xs text-ink-2">筛选项精确匹配并取交集；应用后返回第一页。</span>
      {children}
    </div>
  </form>
}
