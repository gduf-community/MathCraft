import { Check, Download, Plus, Search } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { discoverProviderModels } from '../../../api/modelSettings'
import type {
  DirectModelConfig,
  DirectModelTarget,
  ModelCatalog,
  ModelEntry,
  ModelServiceName,
  ProviderOption,
  ProviderProbeResult,
} from '../../../types/modelSettings'
import { equal, serviceLabels } from './catalog'
import { directApiFormat, directProtocolFields, findDirectModel, newDirectModel, parseDirectHeaders, targetKey, validateDirectModel } from './directCatalog'
import { Field, inputClass, primaryClass, ProviderSelect, secondaryClass } from './Fields'

interface DirectModelEditorProps {
  catalog: ModelCatalog
  live: ModelCatalog
  service: ModelServiceName
  providers: ProviderOption[]
  busy: boolean
  active: boolean
  requestedSelection: DirectModelTarget | null
  draftSources: Record<string, string>
  onChange: (target: DirectModelTarget, model: ModelEntry) => void
  onSave: (target: DirectModelTarget, model: ModelEntry) => void
  onDelete: (target: DirectModelTarget) => void
  onDefault: (target: DirectModelTarget) => void
  onMode: (mode: 'inherit' | 'profiles') => void
  onReset: (target: DirectModelTarget) => void
}

function probeMessage(result: ProviderProbeResult) {
  const status = result.http_status ? `（HTTP ${result.http_status}）` : ''
  const categories: Record<string, string> = {
    invalid_url: '服务地址无效或尚未填写，请检查当前表单',
    invalid_input: '输入不完整，请检查提供方、地址和凭据',
    stale_draft: '旧草稿版本已变化，请重新读取并确认恢复来源',
    missing_credentials: '凭据不足，请补充当前配置所需的授权信息',
    auth_error: '鉴权失败或访问被拒绝，请检查授权与访问权限，不能据此断定密钥错误',
    rate_limited: '请求受到限流，请稍后重试',
    timeout: '获取模型列表超时，请稍后重试',
    unreachable: '无法连接服务，请检查地址、网络与代理',
    unavailable: '此提供方不支持或未提供模型发现接口',
    unsupported: '此提供方不支持模型发现',
    not_supported: '此提供方不支持模型发现',
    not_found: '未找到模型发现接口或当前项的恢复来源，请检查服务地址与旧草稿',
    http_error: '服务返回 HTTP 错误，请检查地址或稍后重试',
    invalid_response: '模型列表响应格式无法识别',
  }
  return `${categories[result.status] ?? '未能获取模型列表，请检查当前配置'}${status}。仍可手动填写模型标识并保存。`
}

export function DirectModelEditor({
  catalog, live, service, providers, busy, active, requestedSelection, draftSources,
  onChange, onSave, onDelete, onDefault, onMode, onReset,
}: DirectModelEditorProps) {
  const rows = (catalog.services[service]?.profiles ?? []).flatMap((profile) =>
    profile.models.map((model) => ({ profile, model, target: { service, profile_id: profile.id, model_id: model.id } })),
  )
  const [selected, setSelected] = useState('')
  const [query, setQuery] = useState('')
  const [attempted, setAttempted] = useState<Record<string, boolean>>({})
  const [replaceKeys, setReplaceKeys] = useState<Record<string, boolean>>({})
  const [discovery, setDiscovery] = useState<{ identity: string; result?: ProviderProbeResult; error?: string } | null>(null)
  const [discovering, setDiscovering] = useState(false)
  const requestVersion = useRef(0)
  const currentIdentity = useRef('')
  const mounted = useRef(true)
  const detailRef = useRef<HTMLDivElement>(null)
  const railRef = useRef<HTMLElement>(null)
  const id = useId()
  const current = rows.find((row) => targetKey(row.target) === selected) ?? rows[0]
  const target = current?.target
  const model = current?.model
  const config = model?.direct_config
  const provider = providers.find((option) => option.value === config?.binding)
  const apiFormat = config ? directApiFormat(config) : 'auto'
  const wireApi = directProtocolFields(apiFormat).wire_api
  const canSelectWireApi = apiFormat !== 'anthropic' &&
    !!provider?.api_formats?.some((format) => format === 'openai_chat' || format === 'openai_responses')
  const parsedHeaders = parseDirectHeaders(config?.extra_headers)
  const key = target ? targetKey(target) : ''
  const draftUpdatedAt = draftSources[key]
  // 完整字段指纹让任何字段更改立即使旧发现结果失效；未保存密钥仅驻留内存。
  const identity = active && model ? JSON.stringify([key, model, draftUpdatedAt]) : ''
  currentIdentity.current = identity
  const visibleDiscovery = discovery?.identity === identity ? discovery : null
  const saved = target ? findDirectModel(live, target) : undefined
  const dirty = !!model && (!equal(model, saved) || !!draftUpdatedAt)
  const validation = target && model ? validateDirectModel(live, target, model) : null
  const isDefault = !!target && live.services[service]?.active_profile_id === target.profile_id &&
    live.services[service]?.active_model_id === target.model_id
  const taskMode = live.services.task?.mode === 'profiles' ? 'profiles' : 'inherit'
  const source = live.services.llm
  const inherited = source?.profiles.find((profile) => profile.id === source.active_profile_id)?.models
    .find((entry) => entry.id === source.active_model_id)
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const visible = rows.filter(({ model: entry }) => [entry.name, entry.model, entry.direct_config?.binding,
    providers.find((option) => option.value === entry.direct_config?.binding)?.label,
  ].some((value) => value?.toLocaleLowerCase().includes(normalizedQuery)))

  useEffect(() => { if (requestedSelection?.service === service) setSelected(targetKey(requestedSelection)) }, [requestedSelection, service])
  useEffect(() => {
    requestVersion.current += 1
    setDiscovering(false)
    setDiscovery(null)
  }, [identity])
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; requestVersion.current += 1 }
  }, [])

  const revealDetail = () => requestAnimationFrame(() => {
    if (detailRef.current && railRef.current && detailRef.current.getBoundingClientRect().top > railRef.current.getBoundingClientRect().top + 24) {
      detailRef.current.focus({ preventScroll: true })
      detailRef.current.scrollIntoView({ behavior: 'auto', block: 'start' })
    }
  })
  const patch = (value: Partial<ModelEntry>) => {
    if (model && target) onChange(target, { ...model, ...value })
  }
  const patchConfig = (value: Partial<DirectModelConfig>) => {
    if (config) patch({ direct_config: { ...config, ...value } })
  }
  async function discover() {
    if (!target || !config || discovering || parsedHeaders.error !== null) return
    const version = ++requestVersion.current
    const fingerprint = identity
    setDiscovering(true)
    setDiscovery(null)
    try {
      const result = await discoverProviderModels({
        ...config, service, profile_id: target.profile_id, model_id: target.model_id,
        ...(draftUpdatedAt ? { restore_draft: true, draft_updated_at: draftUpdatedAt } : {}),
        extra_headers: parsedHeaders.headers,
      })
      if (mounted.current && requestVersion.current === version && currentIdentity.current === fingerprint)
        setDiscovery({ identity: fingerprint, result })
    } catch {
      // 不显示异常原文；网络与上游正文可能带有请求凭据。
      if (mounted.current && requestVersion.current === version && currentIdentity.current === fingerprint)
        setDiscovery({ identity: fingerprint, error: '获取模型列表请求失败，请检查网络、配置和服务访问权限。仍可手动填写模型标识并保存。' })
    } finally {
      if (mounted.current && requestVersion.current === version && currentIdentity.current === fingerprint) setDiscovering(false)
    }
  }
  const headersValid = parsedHeaders.error === null
  const embeddingChanged = service === 'embedding' && !!saved && !!model &&
    !equal([saved.model, saved.dimension, saved.direct_config?.binding, saved.direct_config?.base_url, saved.direct_config?.api_format, saved.direct_config?.api_version],
      [model.model, model.dimension, config?.binding, config?.base_url, config?.api_format, config?.api_version])

  return <div className="space-y-4">
    {service === 'task' && <div className="settings-card space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap gap-2" role="group" aria-label="任务模型模式">
        {([{ mode: 'inherit', label: '跟随主模型' }, { mode: 'profiles', label: '独立配置' }] as const).map(({ mode, label }) => <button
          key={mode} type="button" className={taskMode === mode ? primaryClass : secondaryClass}
          aria-pressed={taskMode === mode} disabled={busy || taskMode === mode} onClick={() => onMode(mode)}
        >{label}</button>)}
      </div>
      <p className="text-sm leading-6 text-slate-600" role="status">{taskMode === 'inherit'
        ? `当前跟随主语言模型：${inherited?.name || inherited?.model || '尚未配置主模型'}。下方独立配置作为备用，保存不会切换任务模式。`
        : '当前使用独立任务默认配置。切换为跟随主模型会保留全部独立配置。'}</p>
    </div>}
    <div className="@container/model-workspace min-w-0">
      <div className="grid min-w-0 items-start gap-5 @4xl/model-workspace:grid-cols-[minmax(14rem,18rem)_minmax(0,1fr)]">
        <aside ref={railRef} className="min-w-0 space-y-3" aria-label={`${serviceLabels[service]}配置列表`}>
          <button type="button" className={`${primaryClass} flex min-h-11 w-full items-center justify-center gap-2`} disabled={busy} onClick={() => {
            const next = newDirectModel(service)
            onChange(next.target, next.model)
            setSelected(targetKey(next.target))
            setQuery('')
            revealDetail()
          }}><Plus size={16} aria-hidden="true" />添加模型</button>
          <Field label="搜索配置或提供方"><span className="relative block">
            <Search size={16} aria-hidden="true" className="pointer-events-none absolute left-3 top-3 text-slate-400" />
            <input type="search" className={`${inputClass} pl-9!`} placeholder="配置名称、模型标识或提供方" value={query} onChange={(event) => setQuery(event.target.value)} />
          </span></Field>
          <p className="text-xs text-slate-500" role="status">{normalizedQuery ? `找到 ${visible.length} / ${rows.length} 个配置` : `已配置 ${rows.length} 个模型`}</p>
          <div className="max-h-80 space-y-2 overflow-y-auto @4xl/model-workspace:max-h-[36rem]">
            {visible.map(({ model: entry, target: entryTarget }) => {
              const entryKey = targetKey(entryTarget)
              const original = findDirectModel(live, entryTarget)
              const edited = !equal(entry, original) || !!draftSources[entryKey]
              const defaultEntry = live.services[service]?.active_profile_id === entryTarget.profile_id && live.services[service]?.active_model_id === entryTarget.model_id
              return <button key={entryKey} type="button" disabled={busy} aria-pressed={entryKey === key}
                className={`w-full rounded-2xl border p-3 text-left focus-visible:outline-2 focus-visible:outline-blue-500 disabled:opacity-50 ${entryKey === key ? 'border-blue-400 bg-blue-50 ring-1 ring-blue-100' : 'border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/50'}`}
                onClick={() => { setSelected(entryKey); revealDetail() }}>
                <span className="flex flex-wrap items-start justify-between gap-2">
                  <span className="min-w-0 break-all text-sm font-semibold text-slate-800">{entry.name || '未命名配置'}</span>
                  {defaultEntry && <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700"><Check size={12} aria-hidden="true" />默认</span>}
                </span>
                <span className="mt-1 block break-all text-xs leading-5 text-slate-500">{providers.find((option) => option.value === entry.direct_config?.binding)?.label || entry.direct_config?.binding || '待选择提供方'}</span>
                <span className="mt-1 block break-all text-xs text-slate-500">{entry.model || '模型标识待填写'}</span>
                {edited && <span className="mt-2 block text-xs text-amber-700">{draftSources[entryKey] ? '已恢复旧草稿，尚未启用' : original ? '有未保存编辑' : '尚未保存'}</span>}
              </button>
            })}
            {!visible.length && <div className="rounded-2xl border border-dashed border-slate-200 p-4 text-sm leading-6 text-slate-500">
              {rows.length ? '没有匹配的配置，请修改搜索条件。' : '尚未配置模型。点击“添加模型”，在同一表单填写提供方与模型信息。'}
              {!!rows.length && <button type="button" className={`${secondaryClass} mt-3`} onClick={() => setQuery('')}>清除搜索</button>}
            </div>}
          </div>
          <p className="text-xs leading-5 text-slate-500">选择配置只切换编辑对象。默认配置需要在详情中单独设置；切换模型类别会保留本地输入。</p>
        </aside>
        <div ref={detailRef} tabIndex={-1} aria-label="模型配置详情" className="settings-card min-w-0 scroll-mt-6 rounded-2xl border border-slate-200 bg-white p-4 outline-none focus-visible:ring-2 focus-visible:ring-blue-200 sm:p-5">
          {model && config && target ? <form key={key} className="space-y-5" onSubmit={(event) => {
            event.preventDefault()
            setAttempted((previous) => ({ ...previous, [key]: true }))
            if (!validation && !busy && parsedHeaders.error === null)
              onSave(target, { ...model, direct_config: { ...config, extra_headers: parsedHeaders.headers } })
          }}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="break-all text-base font-semibold text-slate-800">{model.name || '新模型配置'}</h3>
              <span className="text-xs text-slate-500">{isDefault ? service === 'task' && taskMode === 'inherit' ? '独立备用默认配置' : '当前默认配置' : saved ? '已保存配置' : '尚未启用'}</span>
            </div>
            {draftUpdatedAt && <p role="status" className="rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-800">当前输入来自您明确恢复的旧草稿。凭据仅按该草稿版本与此项标识恢复；保存当前项后才会正式启用。</p>}
            <fieldset disabled={busy} className="min-w-0 space-y-4 disabled:opacity-70">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="配置名称" note="必填；三类配置全局唯一，区分大小写，保存时去除首尾空白。">
                  <input className={inputClass} required value={model.name ?? ''} aria-invalid={attempted[key] && !model.name?.trim()} onChange={(event) => patch({ name: event.target.value })} />
                </Field>
                <ProviderSelect value={config.binding} options={providers} onChange={(binding) => {
                  const option = providers.find((item) => item.value === binding)
                  patchConfig({ binding, base_url: option?.base_url ?? '', ...directProtocolFields(option?.default_api_format ?? 'auto') })
                }} />
                <Field label="服务地址（Base URL）" note="使用提供方要求的完整服务地址，可修改预填值。">
                  <input className={inputClass} value={config.base_url ?? ''} autoComplete="off" onChange={(event) => patchConfig({ base_url: event.target.value })} />
                </Field>
                <div className="flex min-w-0 flex-col gap-1.5 text-sm font-medium text-slate-700">
                  <label htmlFor={`${id}-key`}>API Key</label>
                  {(config.api_key === '***' || (Array.isArray(config.api_key) && config.api_key.every((value) => value === '***') && config.api_key.length > 0)) && !replaceKeys[key]
                    ? <button id={`${id}-key`} type="button" className={`${secondaryClass} text-left`} onClick={() => setReplaceKeys((previous) => ({ ...previous, [key]: true }))}>••••••••　更换凭据</button>
                    : <input id={`${id}-key`} className={inputClass} type="password" autoComplete="new-password" value={config.api_key === '***' ? '' : Array.isArray(config.api_key) ? config.api_key.every((value) => value === '***') ? '' : config.api_key.join(',') : config.api_key ?? ''} onChange={(event) => patchConfig({ api_key: event.target.value })} />}
                  <div className="flex flex-wrap items-center gap-2">
                    <button type="button" className={`${secondaryClass} text-xs`} onClick={() => patchConfig({ api_key: '' })}>明确清除凭据</button>
                    <span className="text-xs font-normal leading-5 text-slate-500">未更换的掩码保留当前项原值；无鉴权或已有账号授权的提供方可留空。</span>
                  </div>
                  {Array.isArray(config.api_key) && <span className="text-xs font-normal text-slate-500">当前为 Key 池；未改动时整组保留，输入新值会替换整组。</span>}
                </div>
              </div>
              <div className="space-y-3 rounded-xl border border-slate-200 p-3">
                <div className="flex flex-wrap items-center gap-3">
                  <button type="button" className={`${secondaryClass} inline-flex min-h-11 items-center gap-2`} disabled={discovering || !config.binding || !headersValid} onClick={() => void discover()}><Download size={16} aria-hidden="true" />{discovering ? '正在获取模型列表…' : '获取模型列表'}</button>
                  <span className="text-xs leading-5 text-slate-500">仅使用当前表单，手动触发；发现结果不代表推理或嵌入调用能力。</span>
                </div>
                {visibleDiscovery?.error && <p role="alert" className="text-sm leading-6 text-amber-800">{visibleDiscovery.error}</p>}
                {visibleDiscovery?.result && (['connected', 'success', 'ok'].includes(visibleDiscovery.result.status)
                  ? <div className="space-y-2">
                    <p role="status" className="text-sm leading-6 text-slate-600">获取到 {visibleDiscovery.result.models.length} 个模型{visibleDiscovery.result.http_status ? `（HTTP ${visibleDiscovery.result.http_status}）` : ''}。{visibleDiscovery.result.models.length ? '请选择结果或手动填写。' : '列表为空，仍可手动填写。'}尚未验证推理或嵌入能力。</p>
                    {!!visibleDiscovery.result.models.length && <Field label="发现结果"><select className={inputClass} value="" onChange={(event) => { if (event.target.value) patch({ model: event.target.value }) }}><option value="">选择模型标识</option>{visibleDiscovery.result.models.map((entry) => <option key={entry.id} value={entry.id}>{entry.name ? `${entry.name} · ` : ''}{entry.id}</option>)}</select></Field>}
                  </div>
                  : <p role="alert" className="text-sm leading-6 text-amber-800">{probeMessage(visibleDiscovery.result)}</p>)}
                <Field label="模型标识" note="必填；可直接输入，无需获取列表，也不要求出现在列表中。">
                  <input className={inputClass} required value={model.model} onChange={(event) => patch({ model: event.target.value })} />
                </Field>
              </div>
              {service === 'embedding' && <Field label="嵌入维度" note="按模型能力填写正整数，留空沿用自动解析。"><input className={inputClass} type="number" min="1" step="1" value={model.dimension ?? ''} onChange={(event) => patch({ dimension: event.target.value === '' ? '' : Number(event.target.value) })} /></Field>}
              <details className="rounded-xl border border-slate-200 p-3">
                <summary className="cursor-pointer text-sm font-medium text-slate-700 focus-visible:outline-2 focus-visible:outline-blue-500">高级参数</summary>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <Field label="API 协议"><select className={inputClass} value={apiFormat || 'auto'} onChange={(event) => patchConfig(directProtocolFields(event.target.value))}>{[...new Set(['auto', ...(provider?.api_formats ?? []), apiFormat || 'auto'])].map((format) => <option key={format} value={format}>{format}</option>)}</select></Field>
                  <Field label="API Version"><input className={inputClass} value={config.api_version ?? ''} onChange={(event) => patchConfig({ api_version: event.target.value })} /></Field>
                  <Field label="应用 ID（App ID，可选）"><input className={inputClass} autoComplete="off" value={config.app_id ?? ''} onChange={(event) => patchConfig({ app_id: event.target.value })} /></Field>
                  <Field label="代理（Proxy）" note="是否生效取决于提供方适配器。"><input className={inputClass} autoComplete="off" value={config.proxy ?? ''} onChange={(event) => patchConfig({ proxy: event.target.value })} /></Field>
                  <div className="sm:col-span-2"><Field label="额外请求头（Extra Headers）" note="JSON 对象，请求头的值必须是文本；掩码按此项的明确来源保留。"><textarea className={inputClass} rows={3} spellCheck={false} autoComplete="off" aria-invalid={!headersValid} value={typeof config.extra_headers === 'string' ? config.extra_headers : JSON.stringify(config.extra_headers ?? {}, null, 2)} onChange={(event) => patchConfig({ extra_headers: event.target.value })} />{!headersValid && <span role="alert" className="text-xs text-red-700">请输入有效的 JSON 对象，请求头的值必须是文本。</span>}</Field></div>
                  {service !== 'embedding' && canSelectWireApi && <Field label="请求接口（Wire API）" note="与 API 协议同步；自动沿用提供方策略。"><select className={inputClass} value={wireApi} onChange={(event) => patchConfig(directProtocolFields(directApiFormat({ wire_api: event.target.value })))}>{['auto', 'chat_completions', 'responses'].map((value) => <option key={value} value={value}>{value}</option>)}</select></Field>}
                  {service === 'embedding'
                    ? <Field label="支持的维度" note="多个正整数用逗号分隔。"><input className={inputClass} value={Array.isArray(model.supported_dimensions) ? model.supported_dimensions.join(',') : model.supported_dimensions ?? ''} onChange={(event) => patch({ supported_dimensions: event.target.value })} /></Field>
                    : <>
                      <Field label="上下文窗口（Tokens）" note="正整数或留空；手动填写时覆盖自动解析值。"><input className={inputClass} type="number" min="1" step="1" value={model.context_window ?? (typeof model.context_window_tokens === 'number' ? model.context_window_tokens : '')} onChange={(event) => patch({ context_window: event.target.value === '' ? '' : Number(event.target.value), context_window_source: 'manual', ...(event.target.value === '' ? { context_window_tokens: '' } : {}) })} /></Field>
                      <Field label="推理强度" note="由提供方和模型决定实际支持的等级。"><select className={inputClass} value={model.reasoning_effort ?? ''} onChange={(event) => patch({ reasoning_effort: event.target.value })}><option value="">自动</option>{[...new Set(['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', ...(model.reasoning_effort ? [model.reasoning_effort] : [])])].map((value) => <option key={value} value={value}>{value}</option>)}</select></Field>
                    </>}
                </div>
                {service !== 'embedding' && <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  {([{ key: 'tools', label: '工具调用' }, { key: 'vision', label: '视觉输入' }, { key: 'json_output', label: 'JSON 输出' }, { key: 'reasoning', label: '推理能力' }] as const).map(({ key: capability, label }) => <Field key={capability} label={label}>
                    <select className={inputClass} value={typeof model.capabilities?.[capability] === 'boolean' ? String(model.capabilities[capability]) : 'auto'} onChange={(event) => {
                      const capabilities = { ...model.capabilities }
                      if (event.target.value === 'auto') delete capabilities[capability]
                      else capabilities[capability] = event.target.value === 'true'
                      patch({ capabilities })
                    }}><option value="auto">自动（后端能力表）</option><option value="true">支持</option><option value="false">不支持</option></select>
                  </Field>)}
                  <p className="text-xs leading-5 text-slate-500 sm:col-span-2">上述覆盖按提供方能力使用。温度、最大输出等调用参数由具体业务控制；模型发现不验证这些能力。</p>
                </div>}
              </details>
            </fieldset>
            {embeddingChanged && <p role="status" className="rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-800">模型、维度、提供方、地址或协议发生变化，已有知识库索引可能不再兼容，需要在知识库中核实；此处不会自动重建索引。仅更换密钥不改变嵌入身份。</p>}
            {attempted[key] && validation && <p role="alert" className="text-sm text-red-700">{validation}</p>}
            <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
              <button type="submit" className={`${primaryClass} min-h-11`} disabled={busy || !dirty}>保存并启用</button>
              <button type="button" className={`${secondaryClass} min-h-11`} disabled={busy || !saved || isDefault} onClick={() => onDefault(target)}>设为默认</button>
              <button type="button" className={`${secondaryClass} min-h-11`} disabled={busy || !dirty} onClick={() => onReset(target)}>撤销当前项编辑</button>
              <button type="button" className={`${secondaryClass} min-h-11 text-red-700`} disabled={busy} onClick={() => onDelete(target)}>{saved ? '删除配置' : '取消添加'}</button>
            </div>
            <p className="text-xs leading-5 text-slate-500" role="status">{busy ? '正在写入并核实正式状态…' : dirty ? '保存只启用当前配置，其他项的本地编辑会保留；设为默认使用当前项已保存的版本。' : '当前配置与正式状态一致。发现结果仅辅助填写。'}</p>
          </form> : <div className="py-8 text-sm leading-7 text-slate-500">选择已有配置查看详情，或添加一个模型；填写完成后可一次保存并启用。</div>}
        </div>
      </div>
    </div>
  </div>
}
