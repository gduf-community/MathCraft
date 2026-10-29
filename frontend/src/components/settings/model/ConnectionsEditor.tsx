import { ArrowLeft, ArrowRight, Cable, Plus, Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type {
  DiscoveredModel,
  ModelCatalog,
  ModelConnection,
  ProviderOption,
} from '../../../types/modelSettings'
import { newId, referencesTo } from './catalog'
import {
  ConnectionForm,
  Field,
  inputClass,
  primaryClass,
  ProviderSelect,
  secondaryClass,
} from './Fields'
import type { ProviderCapability } from './providerDirectory'
import {
  buildProviderDirectory,
  connectionUsageLabels,
  providerCapabilityLabels,
} from './providerDirectory'

interface ConnectionsEditorProps {
  catalog: ModelCatalog
  providers: ProviderOption[]
  providerServices?: Record<string, ProviderOption[]>
  discovery: { key: string; models: DiscoveredModel[] } | null
  onChange: (catalog: ModelCatalog) => void
  onError: (message: string) => void
  onInvalid: (invalid: boolean) => void
  onDiscover: (connection: ModelConnection, service?: ProviderCapability) => void
  onSelect: () => void
  invalid: boolean
  busy: boolean
}

const cardClass =
  'group flex min-w-0 w-full items-start gap-3 rounded-2xl border border-slate-200 bg-white p-4 text-left transition-colors hover:border-blue-300 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-50'
const badgeClass =
  'rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700'

export function ConnectionsEditor({
  catalog,
  providers,
  providerServices,
  discovery,
  onSelect,
  onChange,
  onError,
  onInvalid,
  onDiscover,
  invalid,
  busy,
}: ConnectionsEditorProps) {
  const connections = catalog.connections ?? []
  const [selectedId, setSelectedId] = useState(
    () =>
      connections.find((item) => discovery?.key === 'connection/' + item.id)?.id ??
      '',
  )
  const [view, setView] = useState<'directory' | 'connection'>(() =>
    selectedId ? 'connection' : 'directory',
  )
  const [query, setQuery] = useState('')
  const [capability, setCapability] = useState<'all' | ProviderCapability>('all')
  const [preferredDiscoveryService, setPreferredDiscoveryService] =
    useState<ProviderCapability>('llm')
  const headingRef = useRef<HTMLHeadingElement>(null)
  const returnFocusRef = useRef<HTMLButtonElement | null>(null)
  const navigatedRef = useRef(false)
  const directory = buildProviderDirectory(providers, providerServices)
  const connection = connections.find((item) => item.id === selectedId)
  const showDetail = view === 'connection' && !!connection
  const hasCapabilityDirectory =
    providerServices?.llm !== undefined || providerServices?.embedding !== undefined
  const activeCapability = hasCapabilityDirectory ? capability : 'all'
  const connectionCapabilities =
    directory.find((item) => item.value === connection?.provider)?.capabilities ?? []
  const discoveryService = connectionCapabilities.includes(preferredDiscoveryService)
    ? preferredDiscoveryService
    : connectionCapabilities[0]
  const providerLabel = (value: string) =>
    directory.find((item) => item.value === value)?.label ?? value
  const search = query.trim().toLocaleLowerCase()
  const matches = (...values: string[]) =>
    values.some((value) => value.toLocaleLowerCase().includes(search))
  const configured = connections.filter((item) =>
    matches(item.name || '', item.provider, providerLabel(item.provider)),
  )
  const addable = directory.filter(
    (item) =>
      item.status !== 'legacy' &&
      item.status !== 'deprecated' &&
      item.value !== 'none',
  )
  const available = addable.filter(
    (item) =>
      matches(item.label, item.value) &&
      (activeCapability === 'all' || item.capabilities.includes(activeCapability)),
  )

  useEffect(() => {
    if (!navigatedRef.current) return
    if (
      !showDetail &&
      returnFocusRef.current?.isConnected &&
      !returnFocusRef.current.disabled
    ) {
      returnFocusRef.current.focus()
    } else headingRef.current?.focus()
  }, [showDetail, selectedId])

  const openConnection = (id: string, trigger: HTMLButtonElement) => {
    navigatedRef.current = true
    returnFocusRef.current = trigger
    if (id !== selectedId) onSelect()
    setSelectedId(id)
    setView('connection')
  }
  const createConnection = (
    provider: ProviderOption,
    trigger: HTMLButtonElement,
  ) => {
    const created: ModelConnection = {
      id: newId('connection'),
      name: provider.label + ' 连接',
      provider: provider.value,
      api_key: '',
      base_url: provider.base_url ?? '',
      api_format: provider.default_api_format ?? 'auto',
      extra_headers: {},
    }
    onChange({ ...catalog, connections: [...connections, created] })
    openConnection(created.id, trigger)
  }
  const patch = (change: Partial<ModelConnection>) =>
    onChange({
      ...catalog,
      connections: connections.map((item) =>
        item.id === connection?.id ? { ...item, ...change } : item,
      ),
    })

  return (
    <fieldset disabled={busy} aria-busy={busy} className="min-w-0">
      <div hidden={showDetail} className="min-w-0 space-y-6">
        <header className="space-y-2">
          <h3
            ref={!showDetail ? headingRef : undefined}
            tabIndex={-1}
            className="text-lg font-semibold text-slate-800"
          >
            提供方
          </h3>
          <p className="text-sm leading-6 text-slate-500">
            管理模型连接，再到模型页面添加模型。同一提供方可以添加多个连接，用于不同账号或服务地址。
          </p>
          <Field label="搜索连接或提供方">
            <span className="flex items-center gap-2">
              <Search
                aria-hidden="true"
                size={16}
                className="shrink-0 text-slate-400"
              />
              <input
                type="search"
                className={inputClass}
                value={query}
                placeholder="搜索连接名称或提供方名称"
                onChange={(event) => setQuery(event.target.value)}
              />
            </span>
          </Field>
        </header>
        {invalid && (
          <p
            role="alert"
            className="settings-note rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
          >
            当前连接有未完成的输入。请重新打开该连接修正后，再切换或添加其他连接。
            {connection && (
              <button
                type="button"
                className={secondaryClass + ' mt-2'}
                onClick={() => setView('connection')}
              >
                继续编辑当前连接
              </button>
            )}
          </p>
        )}
        <section aria-label="已配置连接" className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="font-semibold text-slate-800">已配置</h4>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
              {connections.length} 个连接
            </span>
            <span className="text-xs text-slate-500">当前模型目录编辑</span>
          </div>
          {configured.length ? (
            <div className="grid min-w-0 gap-3 xl:grid-cols-2">
              {configured.map((item) => {
                const usages = connectionUsageLabels(catalog, item.id)
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={cardClass}
                    disabled={busy || (invalid && selectedId !== item.id)}
                    onClick={(event) => openConnection(item.id, event.currentTarget)}
                  >
                    <span className="rounded-xl bg-blue-50 p-2 text-blue-600">
                      <Cable aria-hidden="true" size={20} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block break-words text-sm font-semibold text-slate-800">
                        {item.name || item.provider}
                      </span>
                      <span className="mt-1 block break-words text-xs text-slate-500">
                        {providerLabel(item.provider)} · {item.provider}
                      </span>
                      <span className="mt-3 flex flex-wrap gap-1.5">
                        {usages.length ? (
                          usages.map((usage) => (
                            <span key={usage} className={badgeClass}>
                              {usage}
                            </span>
                          ))
                        ) : (
                          <span className="text-xs text-slate-500">
                            尚未关联模型
                          </span>
                        )}
                      </span>
                    </span>
                    <ArrowRight
                      aria-hidden="true"
                      size={16}
                      className="mt-2 shrink-0 text-slate-400 group-hover:text-blue-600"
                    />
                  </button>
                )
              })}
            </div>
          ) : (
            <p
              role="status"
              className="settings-note rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-5 text-sm text-slate-500"
            >
              {connections.length
                ? '没有匹配的连接，请调整搜索。'
                : '尚未配置连接。从下方选择提供方，添加第一个模型连接。'}
            </p>
          )}
        </section>
        <section
          aria-label="添加提供方"
          className="space-y-3 border-t border-slate-200 pt-5"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h4 className="font-semibold text-slate-800">添加提供方</h4>
            <div aria-label="按提供方能力筛选" className="flex flex-wrap gap-2">
              {(['all', 'llm', 'embedding'] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={activeCapability === value}
                  disabled={busy || (value !== 'all' && !hasCapabilityDirectory)}
                  className={
                    activeCapability === value ? primaryClass : secondaryClass
                  }
                  onClick={() => setCapability(value)}
                >
                  {value === 'all' ? '全部' : providerCapabilityLabels[value]}
                </button>
              ))}
            </div>
          </div>
          <p className="text-xs leading-5 text-slate-500">
            能力来自后端提供方目录，仅表示适配能力；账号权限、具体模型及调用结果以实际服务为准。辅助任务模型使用语言模型能力。
            {!hasCapabilityDirectory && ' 当前未提供分用途目录，暂不能按能力筛选。'}
          </p>
          <p role="status" className="text-xs text-slate-500">
            找到 {available.length} 个提供方
          </p>
          {available.length ? (
            <div className="grid min-w-0 gap-3 xl:grid-cols-2">
              {available.map((provider) => {
                const count = connections.filter(
                  (item) => item.provider === provider.value,
                ).length
                return (
                  <button
                    key={provider.value}
                    type="button"
                    className={cardClass}
                    disabled={busy || invalid}
                    onClick={(event) =>
                      createConnection(provider, event.currentTarget)
                    }
                  >
                    <span className="rounded-xl bg-slate-100 p-2 text-slate-600">
                      <Cable aria-hidden="true" size={20} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block break-words text-sm font-semibold text-slate-800">
                        {provider.label}
                      </span>
                      <span className="mt-1 block break-words text-xs text-slate-500">
                        {provider.value}
                      </span>
                      <span className="mt-3 flex flex-wrap gap-1.5">
                        {provider.capabilities.length ? (
                          provider.capabilities.map((service) => (
                            <span key={service} className={badgeClass}>
                              {providerCapabilityLabels[service]}
                            </span>
                          ))
                        ) : (
                          <span className="text-xs text-slate-500">
                            未提供能力信息
                          </span>
                        )}
                      </span>
                      <span className="mt-2 block text-xs text-slate-500">
                        {count
                          ? '已配置 ' + count + ' 个连接，可继续添加'
                          : '添加连接'}
                      </span>
                    </span>
                    <Plus
                      aria-hidden="true"
                      size={16}
                      className="mt-2 shrink-0 text-blue-600"
                    />
                  </button>
                )
              })}
            </div>
          ) : (
            <div
              role="status"
              className="settings-note space-y-3 rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-5 text-sm text-slate-500"
            >
              <p>
                {addable.length
                  ? '没有匹配的提供方，请调整搜索或能力筛选。'
                  : '后端暂未返回可添加的提供方，请重新读取配置。'}
              </p>
              {(search || capability !== 'all') && (
                <button
                  type="button"
                  className={secondaryClass}
                  onClick={() => {
                    setQuery('')
                    setCapability('all')
                  }}
                >
                  清除搜索与筛选
                </button>
              )}
            </div>
          )}
        </section>
      </div>
      {/* 返回时保留表单挂载，避免丢失尚未通过 JSON 校验的请求头输入。 */}
      {connection && (
        <section
          hidden={!showDetail}
          aria-label="连接配置"
          className="settings-card min-w-0 space-y-5 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5"
        >
          <header className="space-y-3 border-b border-slate-200 pb-4">
            <button
              type="button"
              className={secondaryClass + ' inline-flex items-center gap-2'}
              onClick={() => setView('directory')}
            >
              <ArrowLeft aria-hidden="true" size={16} />
              返回提供方
            </button>
            <h3
              ref={showDetail ? headingRef : undefined}
              tabIndex={-1}
              className="break-words text-lg font-semibold text-slate-800"
            >
              {connection.name || providerLabel(connection.provider)}
            </h3>
            <p className="text-sm leading-6 text-slate-500">
              配置{providerLabel(connection.provider)}
              连接。编辑会保留在当前模型目录中，保存草稿并应用后才影响正式配置。
            </p>
          </header>
          <div key={connection.id} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="连接名称">
                <input
                  className={inputClass}
                  value={connection.name || ''}
                  onChange={(event) => patch({ name: event.target.value })}
                />
              </Field>
              <ProviderSelect
                value={connection.provider}
                options={directory.filter(
                  (option) =>
                    option.status !== 'deprecated' ||
                    option.value === connection.provider,
                )}
                onChange={(provider) => {
                  patch({ provider })
                  onSelect()
                }}
              />
            </div>
            <ConnectionForm
              fields={connection}
              options={directory.filter(
                (item) => item.value === connection.provider,
              )}
              onChange={patch}
              onInvalid={onInvalid}
            />
            <details className="rounded-xl border border-slate-200 p-3">
              <summary className="cursor-pointer text-sm font-medium text-slate-700">
                按用途覆盖地址和适配器
              </summary>
              <div className="mt-4 space-y-4">
                {(['llm', 'embedding'] as const).map((service) => {
                  const override = connection.service_overrides?.[service] ?? {}
                  const change = (fields: Record<string, unknown>) =>
                    patch({
                      service_overrides: {
                        ...connection.service_overrides,
                        [service]: { ...override, ...fields },
                      },
                    })
                  return (
                    <div key={service} className="space-y-3">
                      <label className="flex items-center gap-2 text-sm text-slate-700">
                        <input
                          type="checkbox"
                          checked={override.enabled === true}
                          onChange={(event) =>
                            change({ enabled: event.target.checked })
                          }
                        />
                        {service === 'llm'
                          ? '主语言／辅助任务模型覆盖'
                          : '嵌入模型覆盖'}
                      </label>
                      {override.enabled === true && (
                        <div className="grid gap-3 sm:grid-cols-2">
                          <Field label="适配器 binding（留空沿用 Profile）">
                            <input
                              className={inputClass}
                              value={String(override.binding || '')}
                              onChange={(event) =>
                                change({ binding: event.target.value })
                              }
                            />
                          </Field>
                          <Field label="专用 Base URL">
                            <input
                              className={inputClass}
                              value={String(override.base_url || '')}
                              onChange={(event) =>
                                change({ base_url: event.target.value })
                              }
                            />
                          </Field>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </details>
            <p className="text-xs leading-5 text-slate-500">
              模型发现只检查提供方模型列表接口，不能证明推理、嵌入或全部模型可用。后端不支持的发现方式会显示实际状态。
            </p>
            {connectionCapabilities.length > 1 && (
              <Field label="模型发现用途">
                <select
                  className={inputClass}
                  value={discoveryService}
                  disabled={busy || invalid}
                  onChange={(event) => {
                    setPreferredDiscoveryService(
                      event.target.value === 'embedding' ? 'embedding' : 'llm',
                    )
                    onSelect()
                  }}
                >
                  {connectionCapabilities.map((service) => (
                    <option key={service} value={service}>
                      {providerCapabilityLabels[service]}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={secondaryClass}
                disabled={busy || invalid}
                onClick={() => onDiscover(connection, discoveryService)}
              >
                {busy
                  ? '请求处理中…'
                  : discoveryService
                    ? '发现' + providerCapabilityLabels[discoveryService]
                    : '模型发现（此连接）'}
              </button>
              <button
                type="button"
                className={`${secondaryClass} text-red-700`}
                disabled={busy || invalid}
                onClick={() => {
                  const refs = referencesTo(catalog, connection.id)
                  if (refs.length) {
                    onError(`连接仍被引用，请先解除或更换来源：${refs.join('、')}`)
                    return
                  }
                  if (
                    window.confirm(
                      '删除此共享连接？保存草稿并应用后才会影响正式目录。',
                    )
                  ) {
                    onChange({
                      ...catalog,
                      connections: connections.filter(
                        (item) => item.id !== connection.id,
                      ),
                    })
                    setSelectedId('')
                    setView('directory')
                    onSelect()
                  }
                }}
              >
                删除连接
              </button>
            </div>
            {discovery?.key === `connection/${connection.id}` && (
              <div
                className="space-y-2 rounded-xl bg-blue-50 p-3"
                aria-label="共享连接发现结果"
              >
                <p className="text-xs text-blue-800">
                  此连接的发现结果（仅展示模型标识；未验证推理或嵌入能力）
                </p>
                {discovery.models.length ? (
                  <ul className="max-h-48 space-y-1 overflow-y-auto text-sm text-slate-700">
                    {discovery.models.map((item) => (
                      <li key={item.id} className="break-all">
                        {item.id}
                        {item.services?.length
                          ? ` · ${item.services.join('/')}`
                          : ''}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-slate-500">此连接未返回模型标识。</p>
                )}
              </div>
            )}
            <p className="break-all text-xs text-slate-500">
              引用：{referencesTo(catalog, connection.id).join('、') || '暂无'}
            </p>
          </div>
        </section>
      )}
    </fieldset>
  )
}
