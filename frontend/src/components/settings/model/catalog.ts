import type {
  CatalogRecord,
  ModelCatalog,
  ModelConnection,
  ModelEntry,
  ModelProfile,
  ModelService,
  ModelServiceName,
  ProviderProbeRequest,
} from '../../../types/modelSettings'

export const serviceLabels = {
  llm: '主语言模型',
  task: '辅助任务模型',
  embedding: '嵌入模型',
}
export const emptyService = (): ModelService => ({
  profiles: [],
  active_profile_id: null,
  active_model_id: null,
})
export const newId = (prefix: string) => `${prefix}-${crypto.randomUUID()}`
export const equal = (a: unknown, b: unknown) =>
  JSON.stringify(a) === JSON.stringify(b)
export const record = (value: unknown): CatalogRecord =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as CatalogRecord)
    : {}

export function updateService(
  catalog: ModelCatalog,
  name: string,
  patch: Partial<ModelService>,
): ModelCatalog {
  return {
    ...catalog,
    services: {
      ...catalog.services,
      [name]: { ...(catalog.services[name] ?? emptyService()), ...patch },
    },
  }
}

/** 按后端 connection 语义计算当前表单的有效字段，避免用陈旧的 profile 镜像测试。 */
export function effectiveProfile(
  catalog: ModelCatalog,
  name: string,
  profile: ModelProfile,
): ModelProfile {
  if (profile.provider_ref) {
    const ref = profile.provider_ref
    const source = ref.connection_id
      ? catalog.connections?.find((item) => item.id === ref.connection_id)
      : catalog.services[ref.service ?? '']?.profiles.find(
          (item) => item.id === ref.profile_id,
        )
    if (source)
      return {
        ...profile,
        ...source,
        id: profile.id,
        models: profile.models,
        binding: String(
          source.binding ?? source.provider ?? profile.binding ?? '',
        ),
      }
    return profile
  }
  const connection = catalog.connections?.find(
    (item) => item.id === profile.connection_id,
  )
  if (!connection) return profile
  const override =
    connection.service_overrides?.[name === 'task' ? 'llm' : name]
  const fields = override?.enabled ? override : {}
  let url = String(fields.base_url || connection.base_url || '').trim()
  // model_catalog 为共享 embedding base 补 /embeddings；Gemini 原生端点例外。
  if (url) {
    const nativeGemini =
      name === 'embedding' &&
      /:embedContent(?:\?|$)/.test(profile.base_url || '') &&
      !fields.base_url
    url = nativeGemini
      ? profile.base_url || ''
      : url.replace(/\/+$/, '') + (name === 'embedding' ? '/embeddings' : '')
  } else url = profile.base_url || ''
  const next: ModelProfile = {
    ...profile,
    api_key: connection.api_key,
    api_version: connection.api_version,
    extra_headers: connection.extra_headers,
    base_url: url,
  }
  if ('api_format' in connection) next.api_format = connection.api_format
  if ('proxy' in connection) next.proxy = connection.proxy
  if ('wire_api' in connection) next.wire_api = connection.wire_api
  if (fields.binding) next.binding = String(fields.binding)
  return next
}

export function probePayload(
  catalog: ModelCatalog,
  name: ModelServiceName,
  profile: ModelProfile,
): ProviderProbeRequest {
  const effective = effectiveProfile(catalog, name, profile)
  return {
    binding: effective.binding || 'openai',
    service: name,
    connection_id: profile.connection_id || profile.provider_ref?.connection_id,
    profile_id: profile.id,
    base_url: effective.base_url || '',
    api_key: effective.api_key,
    api_format: effective.api_format || 'auto',
    api_version: effective.api_version || '',
    extra_headers: effective.extra_headers,
    proxy: effective.proxy || '',
  }
}

export function connectionPayload(
  connection: ModelConnection,
  service: 'llm' | 'embedding' = 'llm',
): ProviderProbeRequest {
  const override = connection.service_overrides?.[service]
  const fields = override?.enabled ? override : {}
  return {
    binding: String(fields.binding || connection.provider),
    service,
    connection_id: connection.id,
    base_url: String(fields.base_url || connection.base_url || ''),
    api_key: connection.api_key,
    api_format: connection.api_format || 'auto',
    api_version: connection.api_version || '',
    extra_headers: connection.extra_headers,
    proxy: connection.proxy || '',
  }
}

/** 引用扫描包含未展示服务和 task overrides；删除不隐式重选或解除连接。 */
export function referencesTo(catalog: ModelCatalog, id: string): string[] {
  const paths: string[] = []
  function visit(value: unknown, path: string) {
    if (Array.isArray(value)) {
      value.forEach((entry, index) => visit(entry, `${path}[${index}]`))
      return
    }
    if (!value || typeof value !== 'object') return
    for (const [key, entry] of Object.entries(value)) {
      if (key !== 'id' && /(^|_)(id)$/.test(key) && entry === id)
        paths.push(`${path}.${key}`)
      else if (typeof entry === 'object') visit(entry, `${path}.${key}`)
    }
  }
  visit(catalog, 'catalog')
  return paths
}

export function selectedLabel(catalog: ModelCatalog, name: string): string {
  const service = catalog.services[name]
  const profile = service?.profiles.find(
    (item) => item.id === service.active_profile_id,
  )
  const model = profile?.models.find(
    (item) => item.id === service?.active_model_id,
  )
  return model
    ? `${profile?.name || profile?.binding} / ${model.name || model.model}`
    : '尚未选择活动模型'
}

function referenceIdentity(catalog: ModelCatalog, value: unknown) {
  const ref = record(value)
  if (!Object.keys(ref).length) return null
  const source = ref.connection_id
    ? catalog.connections?.find((item) => item.id === ref.connection_id)
    : catalog.services[String(ref.service || '')]?.profiles.find(
        (item) => item.id === ref.profile_id,
      )
  // 只投影身份字段：来源凭据变化不构成向量空间变化。
  return {
    ref,
    provider: source?.provider,
    binding: source?.binding,
    base_url: source?.base_url,
    api_version: source?.api_version,
    source_service: source?.source_service,
    override: record(source?.service_overrides).embedding,
  }
}

function identities(catalog: ModelCatalog) {
  return (catalog.services.embedding?.profiles ?? []).flatMap((profile) => {
    const effective = effectiveProfile(catalog, 'embedding', profile)
    return profile.models.map((model) => ({
      profile: profile.id,
      id: model.id,
      model: model.model,
      dimension: String(model.dimension ?? ''),
      binding: effective.binding,
      base_url: effective.base_url,
      api_version: effective.api_version,
      profile_ref: referenceIdentity(catalog, profile.provider_ref),
      model_ref: referenceIdentity(catalog, model.provider_ref),
    }))
  })
}
export function embeddingIdentityChanged(
  live: ModelCatalog,
  next: ModelCatalog,
): boolean {
  const proposed = identities(next)
  return identities(live).some(
    (identity) =>
      !equal(
        identity,
        proposed.find(
          (item) =>
            item.id === identity.id && item.profile === identity.profile,
        ),
      ),
  )
}

export function validateCatalog(catalog: ModelCatalog): string | null {
  for (const name of ['llm', 'task', 'embedding'] as const) {
    const service = catalog.services[name]
    if (!service) continue
    for (const profile of service.profiles) {
      if (
        profile.connection_id &&
        !catalog.connections?.some((item) => item.id === profile.connection_id)
      )
        return `${serviceLabels[name]}的连接引用不存在`
      for (const model of profile.models) {
        if (
          name !== 'embedding' &&
          model.context_window !== '' &&
          model.context_window != null &&
          (!Number.isInteger(Number(model.context_window)) ||
            Number(model.context_window) <= 0)
        )
          return '上下文窗口必须是正整数或留空'
        if (!model.model.trim())
          return `${serviceLabels[name]}「${model.name || model.id}」缺少模型标识`
        if (
          name === 'embedding' &&
          model.dimension !== '' &&
          model.dimension != null &&
          (!Number.isInteger(Number(model.dimension)) ||
            Number(model.dimension) <= 0)
        )
          return '嵌入维度必须是正整数或留空'
      }
    }
    if (name === 'task' && service.mode === 'reference') {
      const ref = service.selection
      if (
        !catalog.services.llm?.profiles.some(
          (profile) =>
            profile.id === ref?.profile_id &&
            profile.models.some((model) => model.id === ref.model_id),
        )
      )
        return '辅助任务模型引用不存在，请选择主语言模型目录中的有效模型'
    }
    if (service.active_profile_id || service.active_model_id) {
      const active = service.profiles.find(
        (profile) => profile.id === service.active_profile_id,
      )
      if (
        !active ||
        !active.models.some((model) => model.id === service.active_model_id)
      )
        return `${serviceLabels[name]}的活动选择不完整，请选择有效 Profile 和模型`
    }
  }
  return null
}

/** 不把后端可能包含请求内容的错误原文泄露到提示或日志。 */
export function safeError(error: unknown, catalog?: ModelCatalog): string {
  let message = error instanceof Error ? error.message : '请求失败，请重试'
  const secrets: string[] = []
  function collect(value: unknown, secret = false) {
    if (typeof value === 'string') {
      if (secret && value && value !== '***') secrets.push(value)
      return
    }
    if (Array.isArray(value)) {
      value.forEach((item) => collect(item, secret))
      return
    }
    if (value && typeof value === 'object')
      for (const [key, item] of Object.entries(value))
        collect(
          item,
          secret || /api.?key|token|secret|password|extra_headers/i.test(key),
        )
  }
  collect(catalog)
  for (const secret of secrets.sort((a, b) => b.length - a.length))
    message = message.split(secret).join('（凭据已隐藏）')
  return message.replace(
    /(https?:\/\/)[^\s/@]+:[^\s/@]+@/g,
    '$1（凭据已隐藏）@',
  )
}

export function newModel(): ModelEntry {
  return { id: newId('model'), name: '新模型', model: '' }
}
