import type { OpsAlert, OpsEffectiveConfig, OpsOverview, OpsQuery, OpsRunDetail } from '../../../types/ops'
import { OpsCard, OpsFacts, opsButtonClass, opsLabel, opsNumber, opsTime } from './OpsShared'

const metricLabels: Record<string, string> = {
  ingestion_delay: '采集延迟', write_failures: '摘要写入失败', dropped_events: '事件丢弃',
  phoenix_export_backlog: 'Phoenix 导出积压', alert_evaluation: '告警评估',
  cleanup: '清理结果', notification_failures: '通知失败', mapping_missing: '运行与追踪关联缺失',
  storage_capacity: '存储容量',
}
const monitoringLabels: Record<string, string> = {
  healthy: '健康', degraded: '降级', unavailable: '不可用', unknown: '未知',
  monitoring_unavailable: '监控不可用',
}

export function EffectiveConfig({ config }: { config: OpsEffectiveConfig | null | undefined }) {
  if (config === undefined) return <p className="text-sm text-ink-2">生效配置：未提供</p>
  if (config === null) return <p className="text-sm text-ink-2">生效配置：证据未知</p>
  return <div className="space-y-2"><p className="text-sm font-medium text-ink">生效配置（只读）</p>
    <OpsFacts items={[
      ['warning 阈值', opsNumber(config.warning)], ['critical 阈值', opsNumber(config.critical)],
      ['单位', config.unit ?? '未知'], ['窗口（秒）', opsNumber(config.window_seconds)],
      ['配置来源', config.source ?? '未知'],
    ]} />
  </div>
}

export function SelfMonitoring({ overview, now, onOpenAlerts }: { overview: OpsOverview; now: number; onOpenAlerts: (query?: OpsQuery) => void }) {
  const monitoring = overview.self_monitoring
  const missing = monitoring === undefined ? '未接入' : '证据未知／未采集'
  const metrics = monitoring?.metrics
  const ids = [...new Set([...Object.keys(metricLabels), ...(metrics?.map(metric => metric.metric_id) ?? [])])]
  return <OpsCard title="运维链路健康">
    <p className="mb-4 text-sm text-ink-2">独立观察采集、告警和清理链路；以下状态不等同于业务运行结果。观测过期后按未知展示。</p>
    {monitoring == null && <p role="status" className="mb-3 text-sm text-ink-2">运维自监控{missing}。</p>}
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{ids.map(id => {
      const metric = metrics?.find(item => item.metric_id === id)
      const fresh = !!metric?.observed_at && !!metric.fresh_until
        && Date.parse(metric.observed_at) <= Date.parse(overview.generated_at) && Date.parse(metric.fresh_until) > now
      const status = !metric ? 'unknown' : fresh ? metric.status : 'unknown'
      return <section key={id} className="min-w-0 space-y-3 rounded-lg border border-line bg-page p-3">
        <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-sm font-medium text-ink">{metricLabels[id] ?? id}</h4>
          <span className="rounded-md border border-line px-2 py-1 text-xs text-ink">{monitoringLabels[status]}</span></div>
        <OpsFacts items={[
          ['观测值', metric ? `${opsNumber(metric.value)}${metric.unit ? ` ${metric.unit}` : ''}` : missing],
          ['观测时间', metric ? opsTime(metric.observed_at) : missing],
          ['有效至', metric ? opsTime(metric.fresh_until) : missing],
          ['未知原因', !metric ? missing : !fresh ? '观测已过期或未提供新鲜度证据' : metric.unknown_reason ?? (status === 'unknown' || status === 'monitoring_unavailable' ? '未提供原因' : '无未知原因')],
        ]} />
        <EffectiveConfig config={metric?.effective_config} />
      </section>
    })}</div>
    <div className="mt-3 flex flex-wrap gap-2">
      {[
        ['monitoring_pipeline_failure', '查看监控链路异常'], ['capacity_warning', '查看容量异常'],
        ['notification_failure', '查看通知失败'],
      ].map(([rule, label]) => <button key={rule} type="button" className={opsButtonClass}
        onClick={() => onOpenAlerts({ rule_id: rule })}>{label}（近 24 小时新建）</button>)}
    </div>
    <p className="mt-3 text-xs text-ink-2">阈值和容量水位以服务端实际配置为准；页面不设置默认告警阈值。字段未提供不能解释为零或健康。</p>
  </OpsCard>
}

export function ReviewVersions({ detail }: { detail: OpsRunDetail }) {
  const versions = detail.review_versions
  const missing = versions === undefined ? '未接入' : '证据未知／未采集'
  const required = versions?.required_scopes
  return <OpsCard title="版本与审核范围">
    <OpsFacts items={[
      ['运行摘要版本', String(detail.run.revision)],
      ['最终交付内容集合版本', versions ? versions.final_content_revision ?? '未知' : missing],
      ['要求审核范围', required == null ? missing : required.length ? required.map(opsLabel).join('、') : '明确未要求任何审核范围'],
    ]} />
    <p className="mt-3 text-sm text-ink-2">题目内容版本与运行摘要版本分别记录。题干难度审核通过只覆盖该范围，不代表答案、解析或全面数学正确性通过。</p>
    {versions?.final_questions == null ? <p className="mt-3 text-sm text-ink-2">最终题目版本：{missing}</p>
      : versions.final_questions.length === 0 ? <p className="mt-3 text-sm text-ink-2">已确认最终交付题目集合为空。</p>
        : <ul className="mt-3 space-y-3">{versions.final_questions.map(question => {
          const matching = versions.evidence?.filter(evidence => evidence.question_id === question.question_id
            && question.content_revision != null && evidence.content_revision === question.content_revision)
          const completed = matching?.filter(evidence => evidence.status === 'passed' || evidence.status === 'failed').map(evidence => evidence.scope)
          const passed = matching?.filter(evidence => evidence.status === 'passed'
            && matching.every(other => other.scope !== evidence.scope || other.status === 'passed')).map(evidence => evidence.scope)
          const uncovered = required?.filter(scope => !passed?.includes(scope))
          return <li key={question.question_id} className="rounded-lg border border-line bg-page p-3 text-sm">
            <OpsFacts items={[
              ['题目 ID', question.question_id], ['最终内容版本', question.content_revision ?? '未知'],
              ['当前版本实际完成审核范围', matching == null ? '证据未知' : completed?.length ? [...new Set(completed)].map(opsLabel).join('、') : '尚无当前版本完成审核证据'],
              ['当前版本实际通过范围', matching == null ? '证据未知' : passed?.length ? [...new Set(passed)].map(opsLabel).join('、') : '尚无当前版本明确通过证据'],
              ['要求范围未获通过证据', uncovered == null ? '要求范围未知' : uncovered.length ? uncovered.map(opsLabel).join('、') : required?.length === 0 ? '明确未要求审核范围' : '该题已提供全部要求范围的通过证据'],
            ]} />
          </li>
        })}</ul>}
    <details className="mt-3 rounded-lg border border-line p-3"><summary className="min-h-11 cursor-pointer py-3 text-sm font-medium text-primary">审核证据与内容版本对应关系</summary>
      {versions?.evidence == null ? <p className="text-sm text-ink-2">审核证据：{missing}</p>
        : versions.evidence.length === 0 ? <p className="text-sm text-ink-2">已确认审核证据集合为空。</p>
          : <ul className="space-y-2">{versions.evidence.map((evidence, index) => {
            const question = versions.final_questions?.find(item => item.question_id === evidence.question_id)
            const current = question?.content_revision != null && question.content_revision === evidence.content_revision
            return <li key={`${evidence.question_id}:${evidence.scope}:${index}`} className="rounded-lg bg-page p-3 text-sm">
              <p className="break-all">{evidence.question_id} · 内容版本 {evidence.content_revision ?? '未知'} · {opsLabel(evidence.scope)} · {evidence.status === 'passed' ? '该范围通过' : opsLabel(evidence.status)}</p>
              <p className="mt-1 text-ink-2">{current ? '对应当前最终内容版本' : '不覆盖当前最终内容版本（旧版本或关联未知）'}</p>
            </li>
          })}</ul>}
    </details>
  </OpsCard>
}

const runbooks: Record<string, { owner: string; steps: string }> = {
  dependency_failure: { owner: '依赖观测', steps: '确认平台共享或个人凭据范围，核对最近有效调用、错误分类与连续恢复证据。Phoenix 在线不证明单条追踪可读。' },
  waiting_suspected: { owner: '运行采集', steps: '核对受理和实际开始证据、后台执行状态及同类运行。Redis 键数不能当作持久队列长度；不要手动修改终态。' },
  long_running_suspected: { owner: '出题执行', steps: '检查当前阶段、最后心跳和依赖调用；记录最后可信证据，不在后台强停或代用户重试。' },
  heartbeat_stale: { owner: '运行采集', steps: '区分执行失联与采集器故障，检查进程、最后事件和采集延迟；缺少心跳不能直接宣布业务失败。' },
  run_failure: { owner: '出题执行', steps: '核对权威终态、原因码和关联批次；追踪导出失败不能当作业务失败。轮次关闭不表示本次业务成功。' },
  quality_attention: { owner: '交付质量', steps: '检查最终去重并持久化的题量、题目版本、要求审核范围与实际证据。未知不算跳审；降级事实与执行终态分别判断。' },
  monitoring_pipeline_failure: { owner: '运维自监控', steps: '检查采集延迟、SQL 写入、事件丢弃、Phoenix 有界导出和最近告警评估。监控链路不可用时不能宣布无故障。' },
  capacity_warning: { owner: '容量与清理', steps: '核对实际 warning／critical 水位、单位、窗口、存储和清理结果；配置缺失时先确认配置来源，不猜默认阈值或删除活动摘要。' },
  notification_failure: { owner: '告警与通知', steps: '核对通知写入、积压、失败与轮次关联；通知已读不等于恢复，通知失败不能阻塞正常出题。' },
}

export function AlertGuidance({ alert }: { alert: OpsAlert }) {
  const guide = runbooks[alert.rule_id]
  const guidance = alert.guidance
  const missing = guidance === undefined ? '未接入' : '证据未知'
  return <details className="mt-4 rounded-lg border border-line p-3">
    <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium text-primary">只读排障指引</summary>
    <div className="mt-3 space-y-4">
      <OpsFacts items={[
        ['影响范围', guidance ? guidance.impact ?? '未知' : missing],
        ['责任模块（采集值）', guidance ? guidance.owner_module ?? '未知' : missing],
        ['是否需要人工处理', guidance?.manual_action_required == null ? missing : guidance.manual_action_required ? '需要' : '不需要'],
        ['推荐下一步（采集值）', guidance ? guidance.next_step ?? '未知' : missing],
      ]} />
      <div className="rounded-lg bg-page p-3 text-sm text-ink"><p className="font-medium">固定安全指引{guide ? ` · ${guide.owner}` : ''}</p>
        <p className="mt-2 leading-relaxed">{guide?.steps ?? '当前前端未识别此规则，请联系规则维护者核对含义、影响范围及恢复条件；页面不推断其恢复逻辑。'}</p>
        <p className="mt-2 text-ink-2">指引是前端静态内容，不是实际处理记录。不要修改运行结果、手动放行正文或将通知已读视为故障恢复。</p>
      </div>
      <EffectiveConfig config={alert.effective_config} />
    </div>
  </details>
}
