import type {
  DraftResponse,
  ModelCatalog,
  ModelDraft,
  ModelSettingsResponse,
  ProviderProbeRequest,
  ProviderProbeResult,
} from '../types/modelSettings'
import { settingsRequest } from './settingsHttp'

export async function readModelSettings() {
  const [settings, { draft }] = await Promise.all([
    settingsRequest<ModelSettingsResponse>('/api/settings'),
    settingsRequest<DraftResponse>('/api/settings/draft'),
  ])
  if (!settings.catalog?.services || !settings.providers)
    throw new Error('模型设置响应不完整，请重试')
  return { ...settings, draft }
}

export function saveModelDraft(
  catalog: ModelCatalog,
  draft: ModelDraft | null,
) {
  return settingsRequest<DraftResponse>('/api/settings/draft', {
    method: 'PUT',
    body: JSON.stringify({ catalog, extensions: draft?.extensions ?? {} }),
  })
}

export function discardModelDraft() {
  return settingsRequest<DraftResponse>('/api/settings/draft', {
    method: 'DELETE',
  })
}

export function applyModelDraft() {
  // 必须无 body：掩码对应的凭据可能仅存在于已存草稿中。
  return settingsRequest<{ catalog: ModelCatalog }>('/api/settings/apply', {
    method: 'POST',
  })
}

export function discoverProviderModels(payload: ProviderProbeRequest) {
  return settingsRequest<ProviderProbeResult>('/api/settings/test-provider', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchLanguageModels(payload: ProviderProbeRequest) {
  return settingsRequest<{ models: ProviderProbeResult['models'] }>(
    '/api/settings/fetch-models',
    {
      method: 'POST',
      body: JSON.stringify({
        binding: payload.binding,
        base_url: payload.base_url,
        api_key: payload.api_key,
        api_format: payload.api_format,
        service: payload.service,
        profile_id: payload.profile_id,
      }),
    },
  )
}
