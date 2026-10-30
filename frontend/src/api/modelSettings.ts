import type {
  DirectModelResponse,
  DirectModelTarget,
  DraftResponse,
  ModelCatalog,
  ModelDraft,
  ModelSettingsResponse,
  ProviderProbeRequest,
  ProviderProbeResult,
  SaveDirectModelRequest,
} from '../types/modelSettings'
import { apiUrl, settingsRequest } from './settingsHttp'

/** 正式目录读取与旧草稿读取分离：旧草稿故障不阻止正式配置加载或保存核实。 */
export async function readLiveModelSettings() {
  const settings = await settingsRequest<ModelSettingsResponse>('/api/settings')
  if (!settings.catalog?.services || !settings.providers)
    throw new Error('模型设置响应不完整，请重试')
  return settings
}

export async function readModelSettings() {
  const [settings, { draft }] = await Promise.all([
    readLiveModelSettings(),
    readModelDraft(),
  ])
  return { ...settings, draft }
}

export function readModelDraft() {
  return settingsRequest<DraftResponse>('/api/settings/draft')
}

export function readDirectModelDraft() {
  return settingsRequest<DraftResponse>('/api/settings/direct-model/draft')
}

export function saveModelDraft(catalog: ModelCatalog, draft: ModelDraft | null) {
  return settingsRequest<DraftResponse>('/api/settings/draft', {
    method: 'PUT',
    body: JSON.stringify({ catalog, extensions: draft?.extensions ?? {} }),
  })
}

export function discardModelDraft() {
  return settingsRequest<DraftResponse>('/api/settings/draft', { method: 'DELETE' })
}

export function applyModelDraft() {
  return settingsRequest<DirectModelResponse>('/api/settings/apply', { method: 'POST' })
}

export class ModelWriteReadbackError extends Error {}

/** 写入错误只使用受控状态文案，不透传可能包含凭据的响应正文。 */
async function writeDirectModel(path: string, payload: unknown): Promise<DirectModelResponse> {
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    let failure: unknown
    try {
      failure = await response.json()
    } catch {
      // Only the controlled code below changes the write outcome; all other
      // error bodies, including non-JSON proxy responses, remain undisplayed.
      failure = null
    }
    if (response.status === 503 && failure && typeof failure === 'object' &&
      'detail' in failure && failure.detail && typeof failure.detail === 'object' &&
      'code' in failure.detail && failure.detail.code === 'model_write_committed_readback_failed') {
      throw new ModelWriteReadbackError('服务端已完成写入，但正式状态暂时无法读回（HTTP 503）')
    }
    const categories: Record<number, string> = {
      400: '配置缺少必要信息或当前操作不满足条件，请核对表单与默认配置',
      401: '设置访问需要授权，请确认当前登录状态',
      403: '当前授权无权修改设置',
      404: '配置或所选旧草稿来源已不存在，请重新读取并确认',
      409: '配置名称或引用约束冲突，或所选旧草稿版本已变化；请核对名称、引用和恢复来源',
      422: '请求字段格式不正确，请核对配置内容',
      429: '请求过于频繁，请稍后重试',
    }
    throw new Error(`${categories[response.status] ?? '服务未完成配置写入，请稍后重试'}（HTTP ${response.status}）`)
  }
  try {
    return await response.json() as DirectModelResponse
  } catch {
    throw new ModelWriteReadbackError('写入请求已成功，但响应无法解析')
  }
}

export function saveDirectModel(payload: SaveDirectModelRequest) {
  return writeDirectModel('/api/settings/direct-model', payload)
}

export function deleteDirectModel(payload: DirectModelTarget) {
  return writeDirectModel('/api/settings/direct-model/delete', payload)
}

export function setDefaultDirectModel(payload: DirectModelTarget) {
  return writeDirectModel('/api/settings/direct-model/default', payload)
}

export function setDirectTaskMode(mode: 'inherit' | 'profiles') {
  return writeDirectModel('/api/settings/direct-model/task-mode', { mode })
}

/** 上游正文可能包含凭据；HTTP 失败只显示类别和真实状态。 */
async function requestProviderDiscovery(payload: ProviderProbeRequest, path: string): Promise<ProviderProbeResult> {
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    return {
      status: response.status === 401 || response.status === 403 ? 'auth_error'
        : response.status === 429 ? 'rate_limited'
          : response.status === 400 || response.status === 422 ? 'invalid_input'
            : response.status === 404 ? 'not_found'
              : response.status === 409 ? 'stale_draft' : 'http_error',
      models: [],
      http_status: response.status,
    }
  }
  const result = await response.json() as ProviderProbeResult
  if (typeof result.status !== 'string' || !Array.isArray(result.models))
    throw new Error('模型发现响应不完整，仍可手动填写模型标识并保存')
  return result
}

export function discoverProviderModels(payload: ProviderProbeRequest) {
  return requestProviderDiscovery(payload, '/api/settings/test-provider')
}

export function fetchLanguageModels(payload: ProviderProbeRequest) {
  return requestProviderDiscovery(payload, '/api/settings/fetch-models')
}
