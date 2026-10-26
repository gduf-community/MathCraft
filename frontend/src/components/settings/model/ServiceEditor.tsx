import { useState } from 'react'
import type {
  ModelCatalog,
  ModelEntry,
  ModelProfile,
  ModelServiceName,
  ProviderOption,
} from '../../../types/modelSettings'
import {
  emptyService,
  newId,
  newModel,
  referencesTo,
  selectedLabel,
  serviceLabels,
  updateService,
} from './catalog'
import {
  ConnectionForm,
  Field,
  inputClass,
  ProviderSelect,
  secondaryClass,
} from './Fields'

interface ServiceEditorProps {
  catalog: ModelCatalog
  live: ModelCatalog
  name: ModelServiceName
  providers: ProviderOption[]
  onChange: (catalog: ModelCatalog) => void
  onError: (message: string) => void
  onInvalid: (invalid: boolean) => void
  invalid: boolean
  onDiscover: (profile: ModelProfile, useFetch: boolean) => void
  discovery: {
    key: string
    models: { id: string; services?: string[] }[]
  } | null
  canFetch: (profile: ModelProfile) => boolean
  busy: boolean
}

export function ServiceEditor({
  catalog,
  live,
  name,
  providers,
  onChange,
  onError,
  onInvalid,
  invalid,
  onDiscover,
  discovery,
  canFetch,
  busy,
}: ServiceEditorProps) {
  const service = catalog.services[name] ?? emptyService()
  const [profileId, setProfileId] = useState(
    service.active_profile_id ?? service.profiles[0]?.id ?? '',
  )
  const profile =
    service.profiles.find((item) => item.id === profileId) ??
    service.profiles[0]
  const [modelId, setModelId] = useState(service.active_model_id ?? '')
  const model =
    profile?.models.find((item) => item.id === modelId) ?? profile?.models[0]
  const patchService = (patch: Parameters<typeof updateService>[2]) =>
    onChange(updateService(catalog, name, patch))
  const patchProfile = (patch: Partial<ModelProfile>) =>
    patchService({
      profiles: service.profiles.map((item) =>
        item.id === profile?.id ? { ...item, ...patch } : item,
      ),
    })
  const patchModel = (patch: Partial<ModelEntry>) => {
    if (profile && model)
      patchProfile({
        models: profile.models.map((item) =>
          item.id === model.id ? { ...item, ...patch } : item,
        ),
      })
  }
  const remove = (id: string, action: () => void) => {
    const refs = referencesTo(catalog, id)
    if (refs.length) {
      onError(`此项目仍被引用，请先更换活动选择或解除引用：${refs.join('、')}`)
      return
    }
    if (
      window.confirm('删除该配置？保存草稿后才会持久化，应用后才会正式生效。')
    )
      action()
  }
  const addModel = (modelName = '') => {
    if (!profile) return
    const entry = {
      ...newModel(),
      ...(name === 'embedding'
        ? { dimension: '', supported_dimensions: '' }
        : {}),
      ...(modelName ? { name: modelName, model: modelName } : {}),
    }
    patchProfile({ models: [...profile.models, entry] })
    setModelId(entry.id)
  }
  const activeProfile = service.profiles.find(
    (item) => item.id === service.active_profile_id,
  )
  const llm = catalog.services.llm
  return (
    <div className="space-y-5">
      {name === 'task' && (
        <section className="rounded-2xl border border-blue-200 bg-blue-50 p-4 space-y-3">
          <Field label="辅助任务模型来源">
            <select
              className={inputClass}
              value={service.mode ?? 'profiles'}
              onChange={(event) => patchService({ mode: event.target.value })}
            >
              <option value="inherit">跟随主模型（推荐）</option>
              <option value="reference">引用现有主语言模型</option>
              <option value="profiles">独立配置辅助任务模型</option>
            </select>
          </Field>
          {service.mode === 'inherit' && (
            <div className="space-y-1 text-sm text-blue-900">
              <p className="font-semibold">
                跟随主模型 · 每次运行时采用当前正式主语言模型
              </p>
              <p>当前正式解析：{selectedLabel(live, 'llm')}</p>
              <p>
                本页草稿主模型：{selectedLabel(catalog, 'llm')}
                （应用后供后续调用使用）
              </p>
              <p className="text-xs">
                独立配置仍保留，切回时可继续编辑；不会复制某次主模型的参数。
              </p>
            </div>
          )}
          {service.mode === 'reference' && (
            <Field label="引用的模型">
              <select
                className={inputClass}
                value={JSON.stringify([
                  service.selection?.profile_id ?? '',
                  service.selection?.model_id ?? '',
                ])}
                onChange={(event) => {
                  const [profile_id, model_id] = JSON.parse(
                    event.target.value,
                  ) as [string, string]
                  patchService({
                    selection: { ...service.selection, profile_id, model_id },
                  })
                }}
              >
                <option value={JSON.stringify(['', ''])}>
                  请选择已配置的主语言模型
                </option>
                {llm?.profiles
                  .filter((item) => !item.provider_only)
                  .flatMap((item) =>
                    item.models.map((entry) => (
                      <option
                        key={`${item.id}/${entry.id}`}
                        value={JSON.stringify([item.id, entry.id])}
                      >
                        {item.name || item.binding} /{' '}
                        {entry.name || entry.model}
                      </option>
                    )),
                  )}
              </select>
            </Field>
          )}
        </section>
      )}
      {(name !== 'task' || !service.mode || service.mode === 'profiles') && (
        <>
          <section className="settings-card rounded-2xl border border-slate-200 bg-white p-4 space-y-4">
            <h3 className="font-semibold text-slate-800">活动选择</h3>
            <p className="text-sm text-slate-500">
              正式使用：{selectedLabel(live, name)}
              。下方选择仅在应用草稿后生效。
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="活动 Profile">
                <select
                  className={inputClass}
                  value={service.active_profile_id ?? ''}
                  onChange={(event) => {
                    const selected = service.profiles.find(
                      (item) => item.id === event.target.value,
                    )
                    patchService({
                      active_profile_id: selected?.id || null,
                      active_model_id: selected?.models[0]?.id || null,
                    })
                  }}
                >
                  <option value="">未选择</option>
                  {service.profiles
                    .filter(
                      (item) => !item.provider_only && item.models.length > 0,
                    )
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name || item.binding}
                      </option>
                    ))}
                </select>
              </Field>
              <Field label="活动模型">
                <select
                  className={inputClass}
                  value={service.active_model_id ?? ''}
                  onChange={(event) =>
                    patchService({
                      active_model_id: event.target.value || null,
                    })
                  }
                >
                  <option value="">未选择</option>
                  {activeProfile?.models.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name || item.model}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </section>
          <section className="settings-card rounded-2xl border border-slate-200 bg-white p-4 space-y-4">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-48 flex-1">
                <Field label="编辑 Profile（不改变活动选择）">
                  <select
                    className={inputClass}
                    disabled={invalid}
                    value={profile?.id ?? ''}
                    onChange={(event) => {
                      setProfileId(event.target.value)
                      setModelId('')
                    }}
                  >
                    <option value="" disabled>
                      尚无 Profile
                    </option>
                    {service.profiles.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name || item.binding}
                        {item.provider_only ? '（提供方源）' : ''}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <button
                type="button"
                className={secondaryClass}
                disabled={invalid}
                onClick={() => {
                  const created: ModelProfile = {
                    id: newId(name),
                    name: `新${serviceLabels[name]} Profile`,
                    binding:
                      providers.find((item) => item.status !== 'legacy')
                        ?.value || 'openai',
                    models: [],
                  }
                  patchService({ profiles: [...service.profiles, created] })
                  setProfileId(created.id)
                  setModelId('')
                }}
              >
                新增 Profile
              </button>
            </div>
            {profile ? (
              <div key={profile.id} className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Profile 名称">
                    <input
                      className={inputClass}
                      value={profile.name || ''}
                      onChange={(event) =>
                        patchProfile({ name: event.target.value })
                      }
                    />
                  </Field>
                  <Field label="连接来源">
                    <select
                      className={inputClass}
                      disabled={invalid}
                      value={
                        profile.provider_ref
                          ? 'reference'
                          : profile.connection_id || ''
                      }
                      onChange={(event) => {
                        const connection = catalog.connections?.find(
                          (item) => item.id === event.target.value,
                        )
                        patchProfile({
                          connection_id: connection?.id,
                          provider_ref: undefined,
                          ...(connection
                            ? { binding: connection.provider }
                            : {}),
                        })
                      }}
                    >
                      <option value="">此 Profile 独立连接</option>
                      {profile.provider_ref && (
                        <option value="reference">保留现有提供方引用</option>
                      )}
                      {catalog.connections?.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name || item.provider}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <ProviderSelect
                  value={profile.binding || ''}
                  options={providers}
                  onChange={(binding) => patchProfile({ binding })}
                />
                {profile.connection_id || profile.provider_ref ? (
                  <p className="settings-note text-sm text-blue-700">
                    凭据与地址从连接来源继承，请在「提供方与连接」编辑来源。现有引用及额外字段会保留。切换为独立连接后可编辑本
                    Profile 的连接字段。
                  </p>
                ) : (
                  <ConnectionForm
                    key={profile.id}
                    fields={profile}
                    options={providers}
                    onChange={patchProfile}
                    onInvalid={onInvalid}
                  />
                )}
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={secondaryClass}
                    disabled={busy || invalid || !!profile.provider_ref}
                    onClick={() => onDiscover(profile, false)}
                  >
                    模型发现（当前表单）
                  </button>
                  {name !== 'embedding' && (
                    <button
                      type="button"
                      className={secondaryClass}
                      disabled={busy || invalid || !canFetch(profile)}
                      onClick={() => onDiscover(profile, true)}
                    >
                      获取语言模型列表
                    </button>
                  )}
                  <button
                    type="button"
                    className={`${secondaryClass} text-red-700`}
                    disabled={invalid}
                    onClick={() =>
                      remove(profile.id, () => {
                        patchService({
                          profiles: service.profiles.filter(
                            (item) => item.id !== profile.id,
                          ),
                        })
                        setProfileId('')
                      })
                    }
                  >
                    删除 Profile
                  </button>
                </div>
                <p className="text-xs leading-5 text-slate-500">
                  发现只检查模型列表接口，不调用推理或嵌入。列表获取接口仅支持
                  llm/task；草稿掩码、Key
                  池、额外请求头或引用无法按该接口安全恢复时，请使用当前表单模型发现。现有提供方引用可在来源处发现。
                </p>
                <div className="border-t border-slate-100 pt-4 space-y-4">
                  <div className="flex flex-wrap items-end gap-3">
                    <div className="min-w-48 flex-1">
                      <Field label="编辑模型">
                        <select
                          className={inputClass}
                          value={model?.id ?? ''}
                          onChange={(event) => setModelId(event.target.value)}
                        >
                          <option value="" disabled>
                            尚无模型
                          </option>
                          {profile.models.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.name || item.model || '未填写模型'}
                            </option>
                          ))}
                        </select>
                      </Field>
                    </div>
                    <button
                      type="button"
                      className={secondaryClass}
                      onClick={() => addModel()}
                    >
                      手动添加模型
                    </button>
                  </div>
                  {discovery?.key === `${name}/${profile.id}` && (
                    <div className="rounded-xl bg-blue-50 p-3 space-y-2">
                      <p className="text-xs text-blue-800">
                        发现结果（点击添加；模型类别和实际调用权限仍需核实）
                      </p>
                      <div className="flex max-h-48 flex-wrap gap-2 overflow-y-auto">
                        {discovery.models.map((item) => (
                          <button
                            type="button"
                            key={item.id}
                            className={secondaryClass}
                            disabled={profile.models.some(
                              (entry) => entry.model === item.id,
                            )}
                            onClick={() => addModel(item.id)}
                          >
                            {item.id}
                            {item.services?.length
                              ? ` · ${item.services.join('/')}`
                              : ''}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {model && (
                    <div key={model.id} className="space-y-4">
                      <div className="grid gap-4 sm:grid-cols-2">
                        <Field label="模型名称">
                          <input
                            className={inputClass}
                            value={model.name || ''}
                            onChange={(event) =>
                              patchModel({ name: event.target.value })
                            }
                          />
                        </Field>
                        <Field label="模型标识（服务端 Model ID）">
                          <input
                            className={inputClass}
                            value={model.model}
                            onChange={(event) =>
                              patchModel({ model: event.target.value })
                            }
                          />
                        </Field>
                        {name === 'embedding' ? (
                          <>
                            <Field
                              label="嵌入维度"
                              note="留空由适配器默认处理；填写时必须为正整数。模型发现不会测量维度。"
                            >
                              <input
                                className={inputClass}
                                type="number"
                                min="1"
                                step="1"
                                list={`dimensions-${model.id}`}
                                value={model.dimension ?? ''}
                                onChange={(event) =>
                                  patchModel({
                                    dimension:
                                      event.target.value === ''
                                        ? ''
                                        : Number(event.target.value),
                                  })
                                }
                              />
                              <datalist id={`dimensions-${model.id}`}>
                                {(Array.isArray(model.supported_dimensions)
                                  ? model.supported_dimensions
                                  : String(
                                      model.supported_dimensions || '',
                                    ).split(',')
                                )
                                  .filter(Boolean)
                                  .map((value) => (
                                    <option key={value} value={value} />
                                  ))}
                              </datalist>
                            </Field>
                            <Field
                              label="已知支持维度（逗号分隔）"
                              note="这是目录元数据，手动编辑不代表服务已验证支持。"
                            >
                              <input
                                className={inputClass}
                                value={
                                  Array.isArray(model.supported_dimensions)
                                    ? model.supported_dimensions.join(',')
                                    : model.supported_dimensions || ''
                                }
                                onChange={(event) =>
                                  patchModel({
                                    supported_dimensions: event.target.value,
                                  })
                                }
                              />
                            </Field>
                          </>
                        ) : (
                          <>
                            <Field
                              label="上下文窗口（Tokens）"
                              note="留空交由后端解析；人工指定后覆盖目录中的默认窗口。"
                            >
                              <input
                                className={inputClass}
                                type="number"
                                min="1"
                                step="1"
                                value={
                                  model.context_window ??
                                  (typeof model.context_window_tokens ===
                                  'number'
                                    ? model.context_window_tokens
                                    : '')
                                }
                                onChange={(event) =>
                                  patchModel({
                                    context_window:
                                      event.target.value === ''
                                        ? ''
                                        : Number(event.target.value),
                                    context_window_source: 'manual',
                                    ...(event.target.value === ''
                                      ? { context_window_tokens: '' }
                                      : {}),
                                  })
                                }
                              />
                            </Field>
                            <Field
                              label="推理强度"
                              note="由提供方和模型决定实际支持的等级。"
                            >
                              <select
                                className={inputClass}
                                value={model.reasoning_effort || ''}
                                onChange={(event) =>
                                  patchModel({
                                    reasoning_effort: event.target.value,
                                  })
                                }
                              >
                                <option value="">自动</option>
                                {[
                                  ...new Set([
                                    'none',
                                    'minimal',
                                    'low',
                                    'medium',
                                    'high',
                                    'xhigh',
                                    'max',
                                    ...(model.reasoning_effort
                                      ? [model.reasoning_effort]
                                      : []),
                                  ]),
                                ].map((value) => (
                                  <option key={value} value={value}>
                                    {value}
                                  </option>
                                ))}
                              </select>
                            </Field>
                          </>
                        )}
                      </div>
                      {name !== 'embedding' && (
                        <>
                          <div className="grid gap-3 sm:grid-cols-2">
                            {(
                              [
                                'tools',
                                'vision',
                                'json_output',
                                'reasoning',
                              ] as const
                            ).map((key) => (
                              <Field
                                key={key}
                                label={
                                  {
                                    tools: '工具调用',
                                    vision: '视觉输入',
                                    json_output: 'JSON 输出',
                                    reasoning: '推理能力',
                                  }[key]
                                }
                              >
                                <select
                                  className={inputClass}
                                  value={
                                    typeof (
                                      model.capabilities as
                                        Record<string, unknown> | undefined
                                    )?.[key] === 'boolean'
                                      ? String(
                                          (
                                            model.capabilities as Record<
                                              string,
                                              unknown
                                            >
                                          )[key],
                                        )
                                      : 'auto'
                                  }
                                  onChange={(event) => {
                                    const capabilities = {
                                      ...(model.capabilities as
                                        Record<string, unknown> | undefined),
                                    }
                                    if (event.target.value === 'auto')
                                      delete capabilities[key]
                                    else
                                      capabilities[key] =
                                        event.target.value === 'true'
                                    patchModel({ capabilities })
                                  }}
                                >
                                  <option value="auto">
                                    自动（后端能力表）
                                  </option>
                                  <option value="true">支持</option>
                                  <option value="false">不支持</option>
                                </select>
                              </Field>
                            ))}
                          </div>
                          <p className="text-xs text-slate-500">
                            此模型目录支持上下文与推理参数；温度、最大输出等调用参数由具体业务配置控制，本页不宣称这些参数会随目录应用。
                          </p>
                        </>
                      )}
                      {!!model.provider_ref && (
                        <p className="text-sm text-blue-700">
                          此模型另有提供方引用，已保留；运行时连接以该引用为准。
                        </p>
                      )}
                      <button
                        type="button"
                        className={`${secondaryClass} text-red-700`}
                        onClick={() =>
                          remove(model.id, () => {
                            patchProfile({
                              models: profile.models.filter(
                                (item) => item.id !== model.id,
                              ),
                            })
                            setModelId('')
                          })
                        }
                      >
                        删除模型
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-500">
                尚无配置。先新增 Profile，再填写连接与模型，最后选择活动模型。
              </p>
            )}
          </section>
        </>
      )}
    </div>
  )
}
