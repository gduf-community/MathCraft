/** 个人模型设置统一复用带会话校验的当前用户 API。 */
export { getModelSettings, saveModelSettings, testDeepSeek, testMinerU } from './backend'
export type { ModelSettings } from './backend'

import type { ProviderProbeRequest, ProviderProbeResult } from '../types/modelSettings'

/** 历史目录编辑器不再挂载；当前后端不提供自定义提供方发现能力。 */
export async function discoverProviderModels(_payload: ProviderProbeRequest): Promise<ProviderProbeResult> {
  return { status: 'unsupported', models: [] }
}
