import type { ConfigValues } from './engineSettings'

export type ParserEngine = 'text_only' | 'mineru' | 'docling' | 'markitdown' | 'pymupdf4llm' | 'liteparse' | 'tika'
export interface ParserEntry { id: string; name: string; available: boolean; description?: string }
export interface ParsingSettingsData {
  engine: ParserEngine
  image_caption: boolean
  engines: Record<ParserEngine, ConfigValues>
  available_engines: ParserEntry[]
  readiness: Partial<Record<ParserEngine, { ready: boolean; reason?: string; message?: string }>>
  installable: string[]
  model_downloadable: string[]
  mineru: { api_token_set: boolean; local_cli?: { found?: boolean; path?: string } }
  docling: { api_token_set: boolean }
}
export type ParsingJobScope = 'generic' | 'mineru'
export interface ParsingJobStatus {
  state: 'idle' | 'running' | 'done' | 'failed' | 'cancelled'
  lines: string[]
  next_cursor: number
  message: string
  kind?: string
  engine?: string
}
export interface MineruDownloadRequest {
  model_type: 'pipeline' | 'vlm' | 'all'
  source: 'huggingface' | 'modelscope'
  endpoint: string
  local_cli_path: string
}
export interface ParsingSettingsProps { onDirtyChange?: (dirty: boolean) => void }
