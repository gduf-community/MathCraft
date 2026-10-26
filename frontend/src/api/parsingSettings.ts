import type { CheckResult, ConfigValues } from '../types/engineSettings'
import type { MineruDownloadRequest, ParserEngine, ParsingJobScope, ParsingJobStatus, ParsingSettingsData } from '../types/parsingSettings'
import { settingsRequest } from './settingsHttp'

const parsing = '/api/settings/document-parsing'
const jobPath = (scope: ParsingJobScope) => scope === 'mineru' ? '/api/settings/mineru/models/download' : `${parsing}/job`
export const getParsingSettings = () => settingsRequest<ParsingSettingsData>(parsing)
export const saveParsingSettings = (engine: ParserEngine, config: ConfigValues, imageCaption: boolean, activeEngine: ParserEngine = engine) => settingsRequest<ParsingSettingsData>(parsing, { method: 'PUT', body: JSON.stringify({ engine: activeEngine, engines: { [engine]: config }, image_caption: imageCaption }) })
export const checkParser = (engine: ParserEngine) => settingsRequest<CheckResult>(`${parsing}/test`, { method: 'POST', body: JSON.stringify({ engine }) })
export const checkDocling = (api_base_url: string, api_token: ConfigValues['api_token']) => settingsRequest<CheckResult>(`${parsing}/docling/test`, { method: 'POST', body: JSON.stringify({ api_base_url, api_token }) })
export const checkTika = (server_url: string) => settingsRequest<CheckResult>(`${parsing}/tika/test`, { method: 'POST', body: JSON.stringify({ server_url }) })
export const checkMineru = (config: ConfigValues) => settingsRequest<CheckResult>('/api/settings/mineru/test', { method: 'POST', body: JSON.stringify(config) })
export const installParser = (engine: ParserEngine) => settingsRequest<CheckResult>(`${parsing}/install`, { method: 'POST', body: JSON.stringify({ engine }) })
export const downloadParserModels = (engine: ParserEngine) => settingsRequest<CheckResult>(`${parsing}/models/download`, { method: 'POST', body: JSON.stringify({ engine }) })
export const downloadMineruModels = (payload: MineruDownloadRequest) => settingsRequest<CheckResult>('/api/settings/mineru/models/download', { method: 'POST', body: JSON.stringify(payload) })
export const getParsingJob = (scope: ParsingJobScope, cursor = 0) => settingsRequest<ParsingJobStatus>(`${jobPath(scope)}/status?cursor=${cursor}`)
export const cancelParsingJob = (scope: ParsingJobScope) => settingsRequest<CheckResult>(`${jobPath(scope)}/cancel`, { method: 'POST' })
