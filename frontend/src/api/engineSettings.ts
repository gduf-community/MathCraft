import type { CheckResult, ConfigEngine, ConfigValues, LightRagModelOption, RagProvider } from '../types/engineSettings'
import { settingsRequest } from './settingsHttp'

const pipelines = '/api/knowledge-bases/rag-pipelines'
export const getEngineProviders = () => settingsRequest<{ providers: RagProvider[] }>('/api/knowledge-bases/rag-providers')
export const getEngineConfig = (engine: ConfigEngine) => settingsRequest<ConfigValues>(`${pipelines}/${engine}/config`)
export const saveEngineConfig = (engine: ConfigEngine, config: ConfigValues) => settingsRequest<ConfigValues>(`${pipelines}/${engine}/config`, { method: 'PUT', body: JSON.stringify(config) })
export const preflightEngine = (engine: ConfigEngine | 'pageindex-oss') => settingsRequest<CheckResult>(`${pipelines}/${engine}/preflight`)
export const saveEngineMode = (engine: string, mode: string) => settingsRequest<{ provider: string; mode: string }>(`/api/knowledge-bases/rag-providers/${encodeURIComponent(engine)}/mode`, { method: 'PUT', body: JSON.stringify({ mode }) })
export const getLightRagModels = () => settingsRequest<{ options: LightRagModelOption[] }>(`${pipelines}/lightrag/model-options`)
export const probeWeKnora = (payload: { server_url: string; api_key: string; knowledge_base_id: string }) => settingsRequest<CheckResult>('/api/knowledge-bases/probe-weknora', { method: 'POST', body: JSON.stringify(payload) })
export const probeKiwix = (payload: { server_url: string; zim_name: string }) => settingsRequest<CheckResult>('/api/knowledge-bases/probe-kiwix', { method: 'POST', body: JSON.stringify(payload) })
