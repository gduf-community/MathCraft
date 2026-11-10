/** 系统检索配置：复用现有认证与会话代次保护，秘密字段只写不读。 */
import { request } from './session'

export type RagService = 'embedding' | 'rerank'
export type RagRebuildStatus = 'idle' | 'queued' | 'running' | 'succeeded' | 'failed'

export interface EmbeddingSettings {
  embedding_model: string
  embedding_base_url: string
  embedding_key_configured: boolean
  embedding_key_masked: string | null
}

export interface AdminRagSettings {
  active: EmbeddingSettings & {
    rerank_model: string
    rerank_base_url: string
    rerank_key_configured: boolean
    rerank_key_masked: string | null
  }
  pending: EmbeddingSettings | null
  vector_store: { backend: 'chroma'; path: string; available: boolean; message: string }
  rebuild: { status: RagRebuildStatus; progress: number; stage: string; error: string | null }
  revision: number
}

export interface SaveAdminRagSettings {
  embedding_model: string
  embedding_base_url: string
  embedding_api_key?: string
  rerank_model: string
  rerank_base_url: string
  rerank_api_key?: string
  revision: number
}

export interface TestAdminRagSettings {
  service: RagService
  model: string
  base_url: string
  api_key?: string
}

const SETTINGS_PATH = '/api/admin/rag-settings'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isEmbedding(value: unknown): value is EmbeddingSettings {
  return isRecord(value) && typeof value.embedding_model === 'string'
    && typeof value.embedding_base_url === 'string'
    && typeof value.embedding_key_configured === 'boolean'
    && (value.embedding_key_masked === null || typeof value.embedding_key_masked === 'string')
}

/** 校验外部响应，避免将无效状态渲染成已生效配置。 */
function parseSettings(value: unknown): AdminRagSettings {
  if (!isRecord(value)) throw new Error('系统检索配置响应无效，请刷新重试')
  const { active, pending, vector_store: store, rebuild, revision } = value
  if (!isEmbedding(active) || !isRecord(active)
    || typeof active.rerank_model !== 'string' || typeof active.rerank_base_url !== 'string'
    || typeof active.rerank_key_configured !== 'boolean'
    || !(active.rerank_key_masked === null || typeof active.rerank_key_masked === 'string')
    || !(pending === null || isEmbedding(pending))
    || !isRecord(store) || store.backend !== 'chroma' || typeof store.path !== 'string'
    || typeof store.available !== 'boolean' || typeof store.message !== 'string'
    || !isRecord(rebuild) || !['idle', 'queued', 'running', 'succeeded', 'failed'].includes(String(rebuild.status))
    || typeof rebuild.progress !== 'number' || !Number.isFinite(rebuild.progress)
    || typeof rebuild.stage !== 'string' || !(rebuild.error === null || typeof rebuild.error === 'string')
    || typeof revision !== 'number' || !Number.isSafeInteger(revision) || revision < 0) {
    throw new Error('系统检索配置响应无效，请刷新重试')
  }
  // 校验完成后按契约构造；不接纳服务端额外返回的秘密字段。
  const status = rebuild.status
  if (status !== 'idle' && status !== 'queued' && status !== 'running'
    && status !== 'succeeded' && status !== 'failed') throw new Error('索引重建状态无效')
  return {
    active: {
      embedding_model: active.embedding_model, embedding_base_url: active.embedding_base_url,
      embedding_key_configured: active.embedding_key_configured, embedding_key_masked: active.embedding_key_masked,
      rerank_model: active.rerank_model, rerank_base_url: active.rerank_base_url,
      rerank_key_configured: active.rerank_key_configured, rerank_key_masked: active.rerank_key_masked,
    },
    pending: pending === null ? null : {
      embedding_model: pending.embedding_model, embedding_base_url: pending.embedding_base_url,
      embedding_key_configured: pending.embedding_key_configured, embedding_key_masked: pending.embedding_key_masked,
    },
    vector_store: { backend: store.backend, path: store.path, available: store.available, message: store.message },
    rebuild: { status, progress: rebuild.progress, stage: rebuild.stage, error: rebuild.error },
    revision,
  }
}

export async function getAdminRagSettings(): Promise<AdminRagSettings> {
  return parseSettings(await request<unknown>(SETTINGS_PATH))
}

export async function saveAdminRagSettings(body: SaveAdminRagSettings): Promise<AdminRagSettings> {
  return parseSettings(await request<unknown>(SETTINGS_PATH, { method: 'PUT', body: JSON.stringify(body) }))
}

export async function testAdminRagSettings(body: TestAdminRagSettings): Promise<{ ok: true; message: string }> {
  const result = await request<unknown>(`${SETTINGS_PATH}/test`, { method: 'POST', body: JSON.stringify(body) })
  if (!isRecord(result) || result.ok !== true || typeof result.message !== 'string') {
    throw new Error('连接测试响应无效，请重试')
  }
  return { ok: true, message: result.message }
}

export async function rebuildAdminRagSettings(revision: number): Promise<AdminRagSettings> {
  return parseSettings(await request<unknown>(`${SETTINGS_PATH}/rebuild`, {
    method: 'POST', body: JSON.stringify({ revision }),
  }))
}
