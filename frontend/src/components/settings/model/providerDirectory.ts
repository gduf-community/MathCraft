import type { ModelCatalog, ProviderOption } from '../../../types/modelSettings'
import { record, serviceLabels } from './catalog'

export type ProviderCapability = 'llm' | 'embedding'
export interface DirectoryProvider extends ProviderOption {
  capabilities: ProviderCapability[]
}
export const providerCapabilityLabels = {
  llm: '语言模型',
  embedding: '嵌入模型',
} as const satisfies Record<ProviderCapability, string>

/** 能力只来自后端两类目录；合并后的 providers 本身不携带用途信息。 */
export function buildProviderDirectory(
  providers: ProviderOption[],
  providerServices?: Record<string, ProviderOption[]>,
): DirectoryProvider[] {
  const options = new Map<string, ProviderOption>()
  for (const option of [
    ...providers,
    ...(providerServices?.llm ?? []),
    ...(providerServices?.embedding ?? []),
  ]) {
    const previous = options.get(option.value)
    options.set(
      option.value,
      previous
        ? {
            ...option,
            ...previous,
            api_formats: [
              ...new Set([
                ...(previous.api_formats ?? []),
                ...(option.api_formats ?? []),
              ]),
            ],
          }
        : option,
    )
  }
  return [...options.values()]
    .map((option) => ({
      ...option,
      capabilities: (['llm', 'embedding'] as const).filter((service) =>
        providerServices?.[service]?.some(
          (item) => item.value === option.value && item.status !== 'deprecated',
        ),
      ),
    }))
    .sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'))
}

/** 用途展示沿用目录引用，不将提供方的适配能力当成已配置用途。 */
export function connectionUsageLabels(
  catalog: ModelCatalog,
  connectionId: string,
): string[] {
  const visits = new Set<unknown>()
  function usesConnection(value: unknown): boolean {
    if (!value || typeof value !== 'object' || visits.has(value)) return false
    visits.add(value)
    if (Array.isArray(value)) return value.some(usesConnection)
    const entry = record(value)
    if (entry.connection_id === connectionId) return true
    if (typeof entry.service === 'string' && typeof entry.profile_id === 'string') {
      const source = catalog.services[entry.service]?.profiles.find(
        (profile) => profile.id === entry.profile_id,
      )
      if (usesConnection(source)) return true
    }
    return Object.values(entry).some(usesConnection)
  }
  const usages = new Set<string>()
  for (const [service, value] of Object.entries(catalog.services)) {
    visits.clear()
    if (usesConnection(value)) usages.add(service)
  }
  // 跟随和指定引用也关联到语言模型的连接，保留的独立配置仍计入目录引用。
  const task = catalog.services.task
  const llm = catalog.services.llm
  if (task && (task.mode === 'inherit' || task.mode === 'reference')) {
    const selection =
      task.mode === 'reference'
        ? task.selection
        : {
            profile_id: llm?.active_profile_id,
            model_id: llm?.active_model_id,
          }
    const profile = llm?.profiles.find((item) => item.id === selection?.profile_id)
    const model = profile?.models.find((item) => item.id === selection?.model_id)
    visits.clear()
    if (model && usesConnection({ ...profile, ...model, models: [] }))
      usages.add('task')
  }
  return [...usages].map((service) =>
    service in serviceLabels
      ? serviceLabels[service as keyof typeof serviceLabels]
      : service,
  )
}
