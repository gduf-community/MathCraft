import type {
  DirectModelConfig,
  DirectModelTarget,
  ModelCatalog,
  ModelEntry,
  ModelProfile,
  ModelServiceName,
} from '../../../types/modelSettings'
import { effectiveProfile, emptyService, equal, newId } from './catalog'

export const directServices = ['llm', 'embedding', 'task'] as const
export const targetKey = ({ service, profile_id, model_id }: DirectModelTarget) =>
  JSON.stringify([service, profile_id, model_id])

export function findDirectModel(catalog: ModelCatalog, target: DirectModelTarget) {
  return catalog.services[target.service]?.profiles
    .find((profile) => profile.id === target.profile_id)?.models
    .find((model) => model.id === target.model_id)
}

/** 与后端协议契约一致；未带 api_format 的旧配置沿用 wire_api。 */
export function directApiFormat(config: Pick<DirectModelConfig, 'api_format' | 'wire_api'>) {
  if (config.api_format != null) return config.api_format
  if (config.wire_api === 'responses') return 'openai_responses'
  if (config.wire_api === 'chat_completions') return 'openai_chat'
  return 'auto'
}

/** 显式编辑协议时同时更新兼容字段，避免 UI 与实际调用使用不同接口。 */
export function directProtocolFields(apiFormat: string) {
  return {
    api_format: apiFormat,
    wire_api: apiFormat === 'openai_responses' ? 'responses'
      : apiFormat === 'openai_chat' ? 'chat_completions' : 'auto',
  }
}

export function parseDirectHeaders(value: DirectModelConfig['extra_headers']):
  { headers: Record<string, string>; error: null } | { headers: null; error: string } {
  let parsed: unknown
  try {
    // 可选请求头清空后表示显式移除；非空输入仍必须是合法 JSON 对象。
    parsed = typeof value === 'string' ? (value.trim() ? JSON.parse(value) : {}) : value ?? {}
  } catch {
    return { headers: null, error: '额外请求头不是有效的 JSON 对象' }
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) ||
    Object.values(parsed).some((item) => typeof item !== 'string'))
    return { headers: null, error: '额外请求头必须是值为文本的 JSON 对象' }
  return { headers: parsed as Record<string, string>, error: null }
}

/** 只在旧正式数据/显式恢复旧草稿时投影字段；普通编辑始终以模型自身为单位。 */
export function directConfig(catalog: ModelCatalog, service: ModelServiceName, profile: ModelProfile, model: ModelEntry): DirectModelConfig {
  if (model.direct_config) return model.direct_config
  const effective = effectiveProfile(catalog, service, profile)
  return {
    binding: effective.binding ?? '',
    base_url: effective.base_url ?? '',
    api_key: effective.api_key ?? '',
    api_format: directApiFormat(effective),
    api_version: effective.api_version ?? '',
    extra_headers: effective.extra_headers ?? {},
    proxy: effective.proxy ?? '',
    app_id: effective.app_id ?? '',
    ...(effective.wire_api ? { wire_api: effective.wire_api } : {}),
  }
}

export function editableCatalog(catalog: ModelCatalog): ModelCatalog {
  const services = { ...catalog.services }
  for (const service of directServices) {
    const source = services[service] ?? emptyService()
    services[service] = {
      ...source,
      profiles: source.profiles.map((profile) => ({
        ...profile,
        models: profile.models.map((model) => ({
          ...model,
          direct_config: { ...directConfig(catalog, service, profile, model) },
        })),
      })),
    }
  }
  return { ...catalog, services }
}

export function putDirectModel(catalog: ModelCatalog, target: DirectModelTarget, model: ModelEntry): ModelCatalog {
  const service = catalog.services[target.service] ?? emptyService()
  const existing = service.profiles.some((profile) => profile.id === target.profile_id)
  const profiles = existing ? service.profiles : [...service.profiles, { id: target.profile_id, models: [] }]
  return {
    ...catalog,
    services: {
      ...catalog.services,
      [target.service]: {
        ...service,
        profiles: profiles.map((profile) => profile.id !== target.profile_id ? profile : {
          ...profile,
          models: profile.models.some((entry) => entry.id === model.id)
            ? profile.models.map((entry) => entry.id === model.id ? model : entry)
            : [...profile.models, model],
        }),
      },
    },
  }
}

export function removeLocalModel(catalog: ModelCatalog, target: DirectModelTarget): ModelCatalog {
  const service = catalog.services[target.service]
  if (!service) return catalog
  return {
    ...catalog,
    services: { ...catalog.services, [target.service]: {
      ...service,
      profiles: service.profiles.map((profile) => profile.id === target.profile_id
        ? { ...profile, models: profile.models.filter((model) => model.id !== target.model_id) }
        : profile),
    } },
  }
}

/** 正式状态更新后重放其他项的本地编辑，绝不以整份本地目录覆盖写入结果。 */
export function mergeDirectEdits(previous: ModelCatalog, local: ModelCatalog, next: ModelCatalog, completed?: DirectModelTarget): ModelCatalog {
  let merged = editableCatalog(next)
  for (const service of directServices) {
    for (const profile of local.services[service]?.profiles ?? []) {
      for (const model of profile.models) {
        const target = { service, profile_id: profile.id, model_id: model.id }
        if (completed && targetKey(target) === targetKey(completed)) continue
        if (!equal(model, findDirectModel(previous, target)))
          merged = putDirectModel(merged, target, model)
      }
    }
  }
  return merged
}

export function changedDirectModels(live: ModelCatalog, local: ModelCatalog) {
  return directServices.flatMap((service) => (local.services[service]?.profiles ?? [])
    .flatMap((profile) => profile.models.filter((model) => !equal(model,
      findDirectModel(live, { service, profile_id: profile.id, model_id: model.id }))),
    ))
}

export function newDirectModel(service: ModelServiceName): { target: DirectModelTarget; model: ModelEntry } {
  const id = newId('model')
  return {
    target: { service, profile_id: newId('profile'), model_id: id },
    model: {
      id, name: '', model: '',
      direct_config: {
        binding: '', base_url: '', api_key: '', api_format: 'auto',
        api_version: '', extra_headers: {}, proxy: '', app_id: '',
      },
    },
  }
}

export function validateDirectModel(catalog: ModelCatalog, target: DirectModelTarget, model: ModelEntry): string | null {
  const name = model.name?.trim()
  if (!name) return '请填写配置名称，名称不能只有空白'
  for (const service of directServices) {
    for (const profile of catalog.services[service]?.profiles ?? []) {
      if (profile.models.some((entry) => entry.name?.trim() === name &&
        targetKey({ service, profile_id: profile.id, model_id: entry.id }) !== targetKey(target)))
        return '配置名称已存在，请使用全局唯一的名称（区分大小写）'
    }
  }
  if (!model.direct_config?.binding) return '请选择提供方'
  if (!model.model.trim()) return '请填写模型标识；可以手动输入，无需先获取模型列表'
  for (const [value, label] of [[model.dimension, '嵌入维度'], [model.context_window, '上下文窗口']] as const) {
    if (value != null && value !== '' && (!Number.isInteger(Number(value)) || Number(value) <= 0))
      return `${label}必须为正整数或留空`
  }
  const headers = parseDirectHeaders(model.direct_config.extra_headers)
  if (headers.error) return headers.error
  if (typeof model.supported_dimensions === 'string' && model.supported_dimensions.trim() &&
    model.supported_dimensions.split(/[,，\s]+/).filter(Boolean).some((value) => !Number.isInteger(Number(value)) || Number(value) <= 0))
    return '支持的维度请填写正整数，用逗号分隔'
  return null
}
