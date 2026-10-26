export type ConfigValue = string | number | boolean | null | undefined | ConfigValues | ConfigValue[]
export interface ConfigValues { [key: string]: ConfigValue }
export type ConfigEngine = 'llamaindex' | 'pageindex' | 'ima' | 'graphrag' | 'lightrag' | 'lightrag-server'
export interface RagProvider {
  id: string
  name: string
  description?: string
  configured: boolean
  setup_required?: boolean
  readiness_reason?: string
  modes?: string[]
  default_mode?: string
}
export interface CheckResult { ok: boolean; message?: string; title?: string; detail?: string; error?: string; reachable?: boolean; credentials_ok?: boolean; knowledge_base_found?: boolean; knowledge_base_name?: string; checks?: PreflightCheck[] }
export interface PreflightCheck { key: string; label: string; ok: boolean; detail: string; optional?: boolean }
export interface LightRagModelOption {
  profile_id: string
  model_id: string
  model: string
  label?: string
  supports_vision: boolean
  supported_reasoning_efforts: string[]
}
export interface EngineSettingsProps { initialEngine?: string; onDirtyChange?: (dirty: boolean) => void }
