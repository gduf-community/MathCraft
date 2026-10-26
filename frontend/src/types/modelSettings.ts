/** 模型目录是开放契约；索引签名用于保留后端及其他设置页的扩展字段。 */
export interface CatalogRecord {
  [key: string]: unknown
}
export type ModelServiceName = 'llm' | 'task' | 'embedding'
export interface ModelEntry extends CatalogRecord {
  id: string
  name?: string
  model: string
  dimension?: number | string
  supported_dimensions?: number[] | string
  context_window?: number | string
  reasoning_effort?: string
}
export interface ProviderReference extends CatalogRecord {
  connection_id?: string
  service?: string
  profile_id?: string
}
export interface ConnectionFields extends CatalogRecord {
  base_url?: string
  api_key?: string | string[] | null
  api_version?: string
  app_id?: string
  api_format?: string
  extra_headers?: Record<string, string> | string | null
  proxy?: string
}
export interface ModelConnection extends ConnectionFields {
  id: string
  name?: string
  provider: string
  service_overrides?: Record<string, CatalogRecord>
}
export interface ModelProfile extends ConnectionFields {
  id: string
  name?: string
  binding?: string
  connection_id?: string
  provider_ref?: ProviderReference
  provider_only?: boolean
  models: ModelEntry[]
}
export interface ModelSelection extends CatalogRecord {
  profile_id: string
  model_id: string
}
export interface ModelService extends CatalogRecord {
  profiles: ModelProfile[]
  active_profile_id?: string | null
  active_model_id?: string | null
  mode?: string
  selection?: ModelSelection | null
}
export interface ModelCatalog extends CatalogRecord {
  connections?: ModelConnection[]
  services: Record<string, ModelService>
}
export interface ModelDraft extends CatalogRecord {
  catalog: ModelCatalog | null
  extensions: CatalogRecord
  updated_at?: string
}
export interface ProviderOption {
  value: string
  label: string
  base_url?: string
  status?: string
  auth_mode?: string
  api_formats?: string[]
  default_api_format?: string
  default_dim?: string
}
export interface ModelSettingsResponse {
  catalog: ModelCatalog
  providers: Record<string, ProviderOption[]>
}
export interface DraftResponse {
  draft: ModelDraft | null
}
export interface DiscoveredModel {
  id: string
  name?: string
  services?: string[]
}
export interface ProviderProbeResult {
  status: string
  models: DiscoveredModel[]
  warning?: string
}
export interface ProviderProbeRequest extends ConnectionFields {
  binding: string
  service: ModelServiceName
  connection_id?: string
  profile_id?: string
}
