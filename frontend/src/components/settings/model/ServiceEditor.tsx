import { useEffect, useId, useState } from 'react'
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
  record,
  referencesTo,
  selectedLabel,
  serviceLabels,
  updateService,
} from './catalog'
import {
  ConnectionForm,
  Field,
  inputClass,
  primaryClass,
  ProviderSelect,
  secondaryClass,
} from './Fields'
import { ModelWorkspace } from './ModelWorkspace'

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
  onManageProviders?: () => void
  onSelect?: () => void
  onPendingChange?: (pending: boolean) => void
}

function resolvedTaskLabel(catalog: ModelCatalog) {
  const task = catalog.services.task
  if (task?.mode === 'inherit') return selectedLabel(catalog, 'llm')
  if (task?.mode === 'reference') {
    const profile = catalog.services.llm?.profiles.find(
      (item) => item.id === task.selection?.profile_id,
    )
    const model = profile?.models.find(
      (item) => item.id === task.selection?.model_id,
    )
    return model
      ? `${profile?.name || profile?.binding} / ${model.name || model.model}`
      : '指定引用尚未配置或已失效'
  }
  return selectedLabel(catalog, 'task')
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
  onManageProviders,
  onSelect,
  onPendingChange,
}: ServiceEditorProps) {
  const service = catalog.services[name] ?? emptyService()
  const firstProfile =
    service.profiles.find(
      (item) => item.id === service.active_profile_id && !item.provider_only,
    ) ??
    service.profiles.find(
      (item) => !item.provider_only && item.models.length,
    ) ??
    service.profiles[0]
  const [selected, setSelected] = useState({
    profileId: firstProfile?.id ?? '',
    modelId: service.active_model_id ?? '',
  })
  const [adding, setAdding] = useState(
    !service.profiles.some((item) => !item.provider_only && item.models.length),
  )
  const [pendingProfile, setPendingProfile] = useState<ModelProfile | null>(
    null,
  )
  const [manualModel, setManualModel] = useState('')
  const hasPending = pendingProfile !== null || manualModel !== ''
  useEffect(() => {
    onPendingChange?.(hasPending)
  }, [hasPending, onPendingChange])
  const modeId = useId()
  const modeNoteId = useId()
  const profile =
    service.profiles.find((item) => item.id === selected.profileId) ??
    firstProfile
  const model =
    profile?.models.find((item) => item.id === selected.modelId) ??
    profile?.models[0]
  const patchService = (patch: Parameters<typeof updateService>[2]) =>
    onChange(updateService(catalog, name, patch))
  const patchProfile = (patch: Partial<ModelProfile>) => {
    if (profile)
      patchService({
        profiles: service.profiles.map((item) =>
          item.id === profile.id ? { ...item, ...patch } : item,
        ),
      })
  }
  const patchModel = (patch: Partial<ModelEntry>) => {
    if (profile && model)
      patchProfile({
        models: profile.models.map((item) =>
          item.id === model.id ? { ...item, ...patch } : item,
        ),
      })
  }
  const select = (nextProfile: ModelProfile, nextModel?: ModelEntry) => {
    if (invalid || busy) return
    onSelect?.()
    setSelected({ profileId: nextProfile.id, modelId: nextModel?.id ?? '' })
    setAdding(false)
  }
  const cancelAddition = () => {
    if (invalid || busy) return
    onSelect?.()
    setPendingProfile(null)
    setManualModel('')
    setAdding(false)
  }
  const remove = (ids: string[], action: () => void) => {
    const refs = [...new Set(ids.flatMap((id) => referencesTo(catalog, id)))]
    if (refs.length) {
      onError(`此项目仍被引用，请先更换默认选择或解除引用：${refs.join('、')}`)
      return
    }
    if (
      window.confirm('删除该配置？保存草稿后才会持久化，应用后才会正式生效。')
    ) {
      onSelect?.()
      action()
    }
  }
  // 用当前用途的真实适配器目录判断能力，task 共享 llm 的连接覆盖。
  const connections = (catalog.connections ?? []).flatMap((connection) => {
    const override =
      connection.service_overrides?.[name === 'task' ? 'llm' : name]
    const binding =
      override?.enabled &&
      typeof override.binding === 'string' &&
      override.binding
        ? override.binding
        : connection.provider
    const provider = providers.find(
      (item) =>
        item.value === binding &&
        item.status !== 'legacy' &&
        item.status !== 'deprecated',
    )
    return provider ? [{ connection, binding, provider }] : []
  })
  const chosenConnection = connections.find(
    (item) => item.connection.id === pendingProfile?.connection_id,
  )
  const additionProfile =
    chosenConnection && pendingProfile
      ? (service.profiles.find((item) => item.id === pendingProfile.id) ?? {
          ...pendingProfile,
          binding: chosenConnection.binding,
        })
      : undefined
  const appendModel = (target: ModelProfile, modelName = '') => {
    const identifier = modelName.trim()
    if (identifier && target.models.some((item) => item.model === identifier)) {
      onError('此 Profile 已配置该模型，请从左侧列表选择已有模型。')
      return
    }
    const entry: ModelEntry = {
      ...newModel(),
      ...(name === 'embedding'
        ? { dimension: '', supported_dimensions: '' }
        : {}),
      ...(identifier ? { name: identifier, model: identifier } : {}),
    }
    const next = { ...target, models: [...target.models, entry] }
    patchService({
      profiles: service.profiles.some((item) => item.id === target.id)
        ? service.profiles.map((item) => (item.id === target.id ? next : item))
        : [...service.profiles, next],
    })
    if (adding && target.id === pendingProfile?.id) {
      setPendingProfile(null)
      setManualModel('')
    }
    select(next, entry)
  }
  const sourceLabel = (item: ModelProfile, entry?: ModelEntry) => {
    const reference = entry?.provider_ref
      ? record(entry.provider_ref)
      : item.provider_ref
    const source = reference
      ? reference.connection_id
        ? catalog.connections?.find(
            (connection) => connection.id === reference.connection_id,
          )
        : catalog.services[String(reference.service ?? '')]?.profiles.find(
            (other) => other.id === reference.profile_id,
          )
      : catalog.connections?.find(
          (connection) => connection.id === item.connection_id,
        )
    const binding = String(
      source?.provider || source?.binding || item.binding || '',
    )
    return {
      connection:
        source?.name ||
        (source
          ? binding
          : reference
            ? '现有提供方引用'
            : item.connection_id
              ? '连接引用已失效'
              : `${item.name || 'Profile'} · 独立连接`),
      provider:
        providers.find((option) => option.value === binding)?.label ||
        binding ||
        '未指定提供方',
    }
  }
  const rows = service.profiles
    .filter((item) => !item.provider_only)
    .flatMap((item) =>
      item.models.map((entry) => ({
        profile: item,
        model: entry,
        ...sourceLabel(item, entry),
        isDefault:
          item.id === service.active_profile_id &&
          entry.id === service.active_model_id,
      })),
    )
  const isDefault =
    !!profile &&
    !!model &&
    !profile.provider_only &&
    profile.id === service.active_profile_id &&
    model.id === service.active_model_id
  const llmRows = (catalog.services.llm?.profiles ?? [])
    .filter((item) => !item.provider_only)
    .flatMap((item) =>
      item.models.map((entry) => ({ profile: item, model: entry })),
    )
  const taskReference = JSON.stringify([
    service.selection?.profile_id ?? '',
    service.selection?.model_id ?? '',
  ])
  const taskReferenceValid = llmRows.some(
    (item) =>
      item.profile.id === service.selection?.profile_id &&
      item.model.id === service.selection?.model_id,
  )
  const discoveryControls = (target: ModelProfile) => (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={secondaryClass}
          disabled={busy || invalid || !!target.provider_ref}
          onClick={() => onDiscover(target, false)}
        >
          模型发现（当前表单）
        </button>
        {name !== 'embedding' && (
          <button
            type="button"
            className={secondaryClass}
            disabled={busy || invalid || !canFetch(target)}
            onClick={() => onDiscover(target, true)}
          >
            获取语言模型列表
          </button>
        )}
      </div>
      <p className="text-xs leading-5 text-slate-500">
        模型发现只检查模型列表接口，不调用推理或嵌入，不保证账号权限或具体模型可用。列表获取仅支持语言模型；版本、代理、请求头、Key
        池、掩码或引用不满足接口条件时不可用。现有提供方引用请到来源处发现。
      </p>
      {discovery?.key === `${name}/${target.id}` && (
        <div
          className="space-y-2 rounded-xl bg-blue-50 p-3"
          aria-label="当前模型发现结果"
        >
          <p className="text-xs text-blue-800" role="status">
            {discovery.models.length
              ? '选择标识添加模型；实际类别与调用权限仍需核实。'
              : '未返回模型标识，可手动填写模型。'}
          </p>
          <div className="flex max-h-48 flex-wrap gap-2 overflow-y-auto">
            {discovery.models.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`${secondaryClass} max-w-full break-all text-left`}
                disabled={
                  invalid ||
                  busy ||
                  target.models.some((entry) => entry.model === item.id)
                }
                onClick={() => appendModel(target, item.id)}
              >
                {item.id}
                {item.services?.length ? ` · ${item.services.join('/')}` : ''}
                {target.models.some((entry) => entry.model === item.id)
                  ? '（已添加）'
                  : ''}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
  return (
    // 使用普通 div 承担布局，避免原生 fieldset 与容器查询在动态切换时丢失布局。
    <fieldset disabled={busy} aria-busy={busy} className="contents">
      <legend className="sr-only">{serviceLabels[name]}配置</legend>
      <div className="min-w-0 space-y-5">
        {name === 'task' && (
          <section className="settings-card rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
            <h3 className="font-semibold text-slate-800">辅助任务模型来源</h3>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              为辅助性语言处理统一选择模型。切换来源会保留已有独立配置与引用。
            </p>
            <div className="mt-4 divide-y divide-slate-100 border-t border-slate-100">
              <div className="grid items-start gap-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(14rem,20rem)]">
                <div>
                  <label
                    htmlFor={modeId}
                    className="text-sm font-medium text-slate-800"
                  >
                    模型来源模式
                  </label>
                  <p
                    id={modeNoteId}
                    className="mt-1 text-xs leading-5 text-slate-500"
                  >
                    跟随主模型会在每次运行时采用当时的正式主语言模型；指定引用固定到所选模型。
                  </p>
                </div>
                <select
                  id={modeId}
                  aria-describedby={modeNoteId}
                  className={inputClass}
                  disabled={invalid}
                  value={service.mode ?? 'profiles'}
                  onChange={(event) => {
                    onSelect?.()
                    patchService({ mode: event.target.value })
                  }}
                >
                  <option value="inherit">跟随主模型（推荐）</option>
                  <option value="reference">引用指定主模型</option>
                  <option value="profiles">独立配置</option>
                  {service.mode &&
                    !['inherit', 'reference', 'profiles'].includes(
                      service.mode,
                    ) && (
                      <option value={service.mode}>
                        {service.mode}（现有模式）
                      </option>
                    )}
                </select>
              </div>
              {service.mode === 'reference' && (
                <div className="grid items-start gap-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(14rem,20rem)]">
                  <div>
                    <p className="text-sm font-medium text-slate-800">
                      指定主语言模型
                    </p>
                    <p className="mt-1 text-xs leading-5 text-slate-500">
                      引用现有目录记录，后续切换主模型默认选择不会改变此引用。
                    </p>
                  </div>
                  <Field label="引用的模型">
                    <select
                      className={inputClass}
                      value={taskReference}
                      onChange={(event) => {
                        const [profile_id, model_id] = JSON.parse(
                          event.target.value,
                        ) as [string, string]
                        patchService({
                          selection: {
                            ...service.selection,
                            profile_id,
                            model_id,
                          },
                        })
                      }}
                    >
                      <option value={JSON.stringify(['', ''])}>
                        请选择已配置的主语言模型
                      </option>
                      {!taskReferenceValid &&
                        !!(
                          service.selection?.profile_id ||
                          service.selection?.model_id
                        ) && (
                          <option value={taskReference}>
                            现有引用已失效，请重新选择
                          </option>
                        )}
                      {llmRows.map((item) => (
                        <option
                          key={JSON.stringify([item.profile.id, item.model.id])}
                          value={JSON.stringify([item.profile.id, item.model.id])}
                        >
                          {item.profile.name || item.profile.binding} /{' '}
                          {item.model.name || item.model.model}
                        </option>
                      ))}
                    </select>
                    {!llmRows.length && (
                      <span className="text-xs text-amber-700">
                        主语言模型目录为空，请先配置主语言模型。
                      </span>
                    )}
                  </Field>
                </div>
              )}
              <div className="grid gap-4 py-4 text-sm lg:grid-cols-2">
                <div>
                  <p className="font-medium text-slate-700">当前正式解析</p>
                  <p className="mt-1 break-all text-slate-500">
                    {resolvedTaskLabel(live)}
                  </p>
                </div>
                <div>
                  <p className="font-medium text-slate-700">本页草稿预览</p>
                  <p className="mt-1 break-all text-slate-500">
                    {resolvedTaskLabel(catalog)}
                  </p>
                </div>
              </div>
            </div>
            <p className="text-xs leading-5 text-slate-500">
              本页选择保存并应用后才生效。已有 {service.profiles.length} 个独立
              Profile 保留，切回“独立配置”可继续编辑。
            </p>
          </section>
        )}
        {hasPending &&
          (!adding ||
            (name === 'task' && !!service.mode && service.mode !== 'profiles')) && (
            <div className="settings-note space-y-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              <p role="status">
                {name === 'task' && service.mode && service.mode !== 'profiles'
                  ? '未完成的模型添加输入已保留。切回独立配置后点击“添加模型”可继续，也可明确取消添加。'
                  : '未完成的模型添加输入已保留。点击“添加模型”可继续，也可明确取消添加。'}
              </p>
              <button
                type="button"
                className={secondaryClass}
                disabled={invalid}
                onClick={cancelAddition}
              >
                取消添加
              </button>
            </div>
          )}
        {(name !== 'task' || !service.mode || service.mode === 'profiles') && (
          <>
            <div className="settings-note space-y-1 rounded-xl border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900">
              <p className="break-all">正式使用：{selectedLabel(live, name)}</p>
              <p className="break-all">
                本页草稿默认：{selectedLabel(catalog, name)}
                。保存并应用后才会正式生效。
              </p>
              {name === 'embedding' && (
                <p className="text-xs leading-5">
                  更换嵌入模型、维度或服务身份可能影响向量空间兼容性，应用时将确认影响；默认切换不会自动重建知识库。
                </p>
              )}
              {(service.active_profile_id || service.active_model_id) && (
                <button
                  type="button"
                  className={`${secondaryClass} mt-2`}
                  disabled={invalid}
                  onClick={() =>
                    patchService({
                      active_profile_id: null,
                      active_model_id: null,
                    })
                  }
                >
                  清除草稿默认选择
                </button>
              )}
            </div>
            <ModelWorkspace
              rows={rows}
              selected={{
                profileId: profile?.id ?? '',
                modelId: model?.id ?? '',
              }}
              adding={adding}
              disabled={invalid || busy}
              onAdd={() => {
                onSelect?.()
                setAdding(true)
              }}
              onSelect={select}
              compatibility={
                <>
                  <p className="text-xs leading-5 text-slate-500">
                    保留已有多模型 Profile、独立连接和跨用途引用。编辑共享 Profile
                    参数会影响其中所有模型。
                  </p>
                  <Field label="编辑现有 Profile">
                    <select
                      className={inputClass}
                      disabled={invalid}
                      value={profile?.id ?? ''}
                      onChange={(event) => {
                        const next = service.profiles.find(
                          (item) => item.id === event.target.value,
                        )
                        if (next) select(next)
                      }}
                    >
                      <option value="" disabled>
                        尚无 Profile
                      </option>
                      {service.profiles.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name || item.binding || item.id}
                          {item.provider_only ? '（提供方源）' : ''} ·{' '}
                          {item.models.length} 个模型
                        </option>
                      ))}
                    </select>
                  </Field>
                  <button
                    type="button"
                    className={`${secondaryClass} w-full`}
                    disabled={invalid}
                    onClick={() => {
                      const created: ModelProfile = {
                        id: newId(name),
                        name: `新${serviceLabels[name]} Profile`,
                        binding:
                          providers.find(
                            (item) =>
                              item.status !== 'legacy' &&
                              item.status !== 'deprecated',
                          )?.value || '',
                        models: [],
                      }
                      patchService({ profiles: [...service.profiles, created] })
                      select(created)
                    }}
                  >
                    新增独立 Profile（兼容）
                  </button>
                </>
              }
            >
              {adding ? (
                <div className="space-y-5">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <h3 className="font-semibold text-slate-800">
                      添加{serviceLabels[name]}
                    </h3>
                    <button
                      type="button"
                      className={secondaryClass}
                      disabled={invalid || !onManageProviders}
                      onClick={() => {
                        onSelect?.()
                        onManageProviders?.()
                      }}
                    >
                      管理提供方
                    </button>
                  </div>
                  <Field
                    label="1. 选择已配置的提供方连接"
                    note="仅列出适配器支持当前用途的连接；能力支持不保证账号权限或具体模型可用。"
                  >
                    <select
                      className={inputClass}
                      value={pendingProfile?.connection_id ?? ''}
                      disabled={invalid}
                      onChange={(event) => {
                        const chosen = connections.find(
                          (item) => item.connection.id === event.target.value,
                        )
                        if (!chosen) return
                        onSelect?.()
                        const existing = service.profiles.find(
                          (item) =>
                            item.connection_id === chosen.connection.id &&
                            item.binding === chosen.binding &&
                            !item.provider_ref &&
                            !item.provider_only,
                        )
                        setPendingProfile({
                          id: existing?.id ?? newId(name),
                          name: chosen.connection.name || chosen.provider.label,
                          connection_id: chosen.connection.id,
                          binding: chosen.binding,
                          models: [],
                        })
                      }}
                    >
                      <option value="" disabled={!!pendingProfile}>
                        请选择连接
                      </option>
                      {pendingProfile && !chosenConnection && (
                        <option value={pendingProfile.connection_id} disabled>
                          原连接不再支持当前用途，请重新选择（输入已保留）
                        </option>
                      )}
                      {connections.map(({ connection, provider }) => (
                        <option key={connection.id} value={connection.id}>
                          {connection.name || connection.provider} ·{' '}
                          {provider.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  {!connections.length && (
                    <div className="space-y-3 rounded-xl border border-dashed border-blue-200 bg-blue-50 p-4">
                      <p className="text-sm leading-6 text-slate-600">
                        尚无支持{serviceLabels[name]}
                        的共享连接。请先在提供方页面配置连接，再返回添加模型；已有独立
                        Profile 仍可通过左侧兼容入口编辑。
                      </p>
                      <button
                        type="button"
                        className={primaryClass}
                        disabled={!onManageProviders || invalid}
                        onClick={() => {
                          onSelect?.()
                          onManageProviders?.()
                        }}
                      >
                        前往配置提供方
                      </button>
                      {!onManageProviders && (
                        <p className="text-xs text-slate-500">
                          请从模型与服务导航进入“提供方”。
                        </p>
                      )}
                    </div>
                  )}
                  {pendingProfile && (
                    <div className="space-y-4 border-t border-slate-100 pt-4">
                      <h4 className="text-sm font-semibold text-slate-800">
                        2. 发现模型或手动填写
                      </h4>
                      {additionProfile && discoveryControls(additionProfile)}
                      <Field
                        label="模型标识（服务端 Model ID）"
                        note="发现未返回所需模型时，可填写提供方支持的模型标识。"
                      >
                        <input
                          className={inputClass}
                          value={manualModel}
                          placeholder="输入模型标识"
                          onChange={(event) => setManualModel(event.target.value)}
                        />
                      </Field>
                      <button
                        type="button"
                        className={primaryClass}
                        disabled={
                          invalid || !additionProfile || !manualModel.trim()
                        }
                        onClick={() => {
                          if (additionProfile)
                            appendModel(additionProfile, manualModel)
                        }}
                      >
                        添加到本页草稿
                      </button>
                    </div>
                  )}
                  <button
                    type="button"
                    className={secondaryClass}
                    disabled={invalid}
                    onClick={cancelAddition}
                  >
                    取消添加
                  </button>
                </div>
              ) : profile ? (
                <div className="space-y-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="break-all font-semibold text-slate-800">
                        {model?.name ||
                          model?.model ||
                          profile.name ||
                          '配置 Profile'}
                      </h3>
                      <p className="mt-1 break-all text-xs leading-5 text-slate-500">
                        {sourceLabel(profile, model).connection} ·{' '}
                        {sourceLabel(profile, model).provider}
                      </p>
                    </div>
                    {model && !profile.provider_only && (
                      <button
                        type="button"
                        className={isDefault ? secondaryClass : primaryClass}
                        disabled={invalid || isDefault || !model.model.trim()}
                        onClick={() =>
                          patchService({
                            active_profile_id: profile.id,
                            active_model_id: model.id,
                          })
                        }
                      >
                        {isDefault ? '已是草稿默认' : '设为默认模型'}
                      </button>
                    )}
                  </div>
                  {model ? (
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
                      </div>
                      <details
                        className="rounded-xl border border-slate-200 p-4"
                        open={name === 'embedding'}
                      >
                        <summary className="cursor-pointer text-sm font-semibold text-slate-700">
                          {name === 'embedding'
                            ? '嵌入维度'
                            : '高级模型参数与能力'}
                        </summary>
                        <div className="mt-4 grid gap-4 sm:grid-cols-2">
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
                                          | Record<string, unknown>
                                          | undefined
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
                                          | Record<string, unknown>
                                          | undefined),
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
                      </details>
                      {!!model.provider_ref && (
                        <p className="text-sm leading-6 text-blue-700">
                          此模型另有提供方引用，已保留；运行时连接以该引用为准。
                        </p>
                      )}
                      <button
                        type="button"
                        className={`${secondaryClass} text-red-700`}
                        disabled={invalid}
                        onClick={() =>
                          remove([model.id], () => {
                            patchProfile({
                              models: profile.models.filter(
                                (item) => item.id !== model.id,
                              ),
                            })
                            setSelected({ profileId: profile.id, modelId: '' })
                          })
                        }
                      >
                        删除模型
                      </button>
                    </div>
                  ) : (
                    <p className="rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-500">
                      此 Profile
                      尚无模型。可在下方添加模型，或继续维护连接参数。提供方源不会作为默认模型。
                    </p>
                  )}
                  <details
                    key={profile.id}
                    className="rounded-xl border border-slate-200 p-4"
                    open={!model}
                  >
                    <summary className="cursor-pointer text-sm font-semibold text-slate-700">
                      连接与 Profile（兼容配置）
                    </summary>
                    <div className="mt-4 space-y-4">
                      <p className="text-xs leading-5 text-slate-500">
                        此 Profile 包含 {profile.models.length}{' '}
                        个模型；更改本组连接或提供方会影响它们，内部 ID
                        与其他字段保持不变。
                      </p>
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
                              if (event.target.value === 'reference') return
                              onSelect?.()
                              const chosen = connections.find(
                                (item) => item.connection.id === event.target.value,
                              )
                              if (event.target.value && !chosen) return
                              patchProfile({
                                connection_id: chosen?.connection.id,
                                provider_ref: undefined,
                                ...(chosen ? { binding: chosen.binding } : {}),
                              })
                            }}
                          >
                            <option value="">此 Profile 独立连接</option>
                            {profile.provider_ref && (
                              <option value="reference">
                                保留现有提供方引用
                              </option>
                            )}
                            {profile.connection_id &&
                              !connections.some(
                                (item) =>
                                  item.connection.id === profile.connection_id,
                              ) && (
                                <option value={profile.connection_id}>
                                  {catalog.connections?.some(
                                    (item) => item.id === profile.connection_id,
                                  )
                                    ? '现有连接不支持当前用途（保留引用）'
                                    : '现有连接已失效（保留引用）'}
                                </option>
                              )}
                            {connections.map(({ connection }) => (
                              <option key={connection.id} value={connection.id}>
                                {connection.name || connection.provider}
                              </option>
                            ))}
                          </select>
                        </Field>
                      </div>
                      <ProviderSelect
                        value={profile.binding || ''}
                        options={providers}
                        onChange={(binding) => {
                          onSelect?.()
                          patchProfile({ binding })
                        }}
                      />
                      {profile.connection_id || profile.provider_ref ? (
                        <div className="space-y-3">
                          <p className="text-sm leading-6 text-blue-700">
                            凭据与地址从连接来源继承，请在提供方或原 Profile
                            编辑来源。现有引用及额外字段会保留。切换为独立连接后可编辑本
                            Profile 的连接字段。
                          </p>
                          {onManageProviders && (
                            <button
                              type="button"
                              className={secondaryClass}
                              disabled={invalid}
                              onClick={() => {
                                onSelect?.()
                                onManageProviders()
                              }}
                            >
                              管理提供方
                            </button>
                          )}
                        </div>
                      ) : (
                        <ConnectionForm
                          key={profile.id}
                          fields={profile}
                          options={providers}
                          onChange={(patch) => {
                            onSelect?.()
                            patchProfile(patch)
                          }}
                          onInvalid={onInvalid}
                        />
                      )}
                      {discoveryControls(profile)}
                      <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
                        <button
                          type="button"
                          className={secondaryClass}
                          disabled={invalid}
                          onClick={() => appendModel(profile)}
                        >
                          手动添加到此 Profile
                        </button>
                        <button
                          type="button"
                          className={`${secondaryClass} text-red-700`}
                          disabled={invalid}
                          onClick={() =>
                            remove(
                              [
                                profile.id,
                                ...profile.models.map((item) => item.id),
                              ],
                              () => {
                                patchService({
                                  profiles: service.profiles.filter(
                                    (item) => item.id !== profile.id,
                                  ),
                                })
                                setSelected({ profileId: '', modelId: '' })
                              },
                            )
                          }
                        >
                          删除 Profile 及其模型
                        </button>
                      </div>
                      <p className="break-all text-xs leading-5 text-slate-500">
                        Profile 引用：
                        {referencesTo(catalog, profile.id).join('、') || '暂无'}
                      </p>
                    </div>
                  </details>
                </div>
              ) : (
                <p className="text-sm text-slate-500">
                  请在左侧添加模型或选择已有配置。
                </p>
              )}
            </ModelWorkspace>
          </>
        )}
      </div>
    </fieldset>
  )
}
