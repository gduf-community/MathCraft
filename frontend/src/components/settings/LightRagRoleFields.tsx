import { useEffect, useState } from 'react'
import { getLightRagModels } from '../../api/engineSettings'
import type { ConfigValues, LightRagModelOption } from '../../types/engineSettings'
import { EngineParsingFields, numberField, selectField, settingsError } from './EngineParsingFields'

const roleNames = { extract: '实体提取', keyword: '检索关键词', query: '回答生成', vlm: '视觉理解' } as const
function selectionKey(value: ConfigValues) { return JSON.stringify([value.profile_id ?? '', value.model_id ?? '']) }
function ModelChoice({ label, value, options, onChange, vision = false }: { label: string; value: ConfigValues; options: LightRagModelOption[]; onChange: (value: ConfigValues) => void; vision?: boolean }) {
  const selected = options.find(option => option.profile_id === value.profile_id && option.model_id === value.model_id)
  const choices = options.filter(option => !vision || option.supports_vision)
  return <label className="settings-label block space-y-2">{label}
    <select className="settings-input" value={selectionKey(value)} onChange={event => {
      const option = choices.find(item => JSON.stringify([item.profile_id, item.model_id]) === event.target.value)
      if (option) onChange({ profile_id: option.profile_id, model_id: option.model_id })
    }}>
      {!selected && <option value={selectionKey(value)}>{value.model_id ? `当前模型不可用：${value.model_id}` : '请选择正式模型'}</option>}
      {choices.map(option => <option key={JSON.stringify([option.profile_id, option.model_id])} value={JSON.stringify([option.profile_id, option.model_id])}>{option.label || option.model} · {option.profile_id}</option>)}
    </select>
  </label>
}
export function LightRagRoleFields({ roles, onChange, disabled }: { roles: ConfigValues; onChange: (roles: ConfigValues) => void; disabled: boolean }) {
  const [options, setOptions] = useState<LightRagModelOption[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    async function load() {
      try { const data = await getLightRagModels(); if (active) setOptions(data.options) }
      catch (error) { if (active) setError(settingsError(error)) }
      finally { if (active) setLoading(false) }
    }
    void load()
    return () => { active = false }
  }, [attempt])
  const base = (roles.base ?? {}) as ConfigValues
  return <fieldset disabled={disabled} className="space-y-4 rounded-xl border border-slate-200 p-4">
    <legend className="px-2 font-medium">LightRAG 专用模型与角色</legend>
    <p className="settings-note">选择仅影响此引擎，不修改正式主语言模型。模型选项来自正式目录；视觉角色要求模型支持图像输入。</p>
    {loading && <p role="status">正在读取正式模型选项…</p>}
    {error && <div role="alert" className="settings-error">{error}<button type="button" className="settings-button-secondary ml-2" onClick={() => setAttempt(value => value + 1)}>重试模型列表</button></div>}
    {!loading && !error && options.length === 0 && <p className="settings-note">正式目录暂无可选模型，请先在模型与服务中配置。</p>}
    <ModelChoice label="基础模型" value={base} options={options} onChange={base => onChange({ ...roles, base })} />
    <label className="settings-label block">基础模型推理强度<select className="settings-input mt-2" value={String(base.reasoning_effort ?? '')} onChange={event => onChange({ ...roles, base: { ...base, reasoning_effort: event.target.value || null } })}>
      <option value="">提供方默认</option>{options.find(item => item.profile_id === base.profile_id && item.model_id === base.model_id)?.supported_reasoning_efforts.map(effort => <option key={effort}>{effort}</option>)}
    </select></label>
    {Object.entries(roleNames).map(([key, label]) => {
      const role = (roles[key] ?? { mode: key === 'vlm' ? 'disabled' : 'inherit', max_async: 4, timeout: 240 }) as ConfigValues
      const selection = (role.selection ?? {}) as ConfigValues
      const effective = role.mode === 'model' ? selection : base
      const reasoningOptions = options.find(item => item.profile_id === effective.profile_id && item.model_id === effective.model_id)?.supported_reasoning_efforts ?? []
      return <div key={key} className="space-y-3 border-t border-slate-100 pt-3">
        <h4 className="text-sm font-medium">{label}</h4>
        <EngineParsingFields fields={[selectField('mode', '模型来源', key === 'vlm' ? ['disabled', 'inherit', 'model'] : ['inherit', 'model']), numberField('max_async', '并发上限', 1, 32), numberField('timeout', '超时（秒）', 1, 3600)]} values={role} onChange={(field, value) => onChange({ ...roles, [key]: { ...role, [field]: value, ...(field === 'mode' ? { selection: value === 'model' ? { profile_id: base.profile_id ?? '', model_id: base.model_id ?? '' } : null, ...(value === 'disabled' ? { reasoning_effort: null } : {}) } : {}) } })} />
        {role.mode === 'model' && <ModelChoice label={`${label}模型`} value={selection} options={options} vision={key === 'vlm'} onChange={selection => onChange({ ...roles, [key]: { ...role, selection, reasoning_effort: null } })} />}
        {role.mode !== 'disabled' && <label className="settings-label block">角色推理强度<select className="settings-input mt-2" value={String(role.reasoning_effort ?? '')} onChange={event => onChange({ ...roles, [key]: { ...role, reasoning_effort: event.target.value || null } })}>
          <option value="">继承模型设置</option>{reasoningOptions.map(effort => <option key={effort}>{effort}</option>)}
        </select></label>}
      </div>
    })}
  </fieldset>
}

export function serializeLightRagRoles(roles: ConfigValues): ConfigValues {
  const result: ConfigValues = { base: roles.base }
  for (const key of Object.keys(roleNames)) {
    const role = (roles[key] ?? {}) as ConfigValues
    result[key] = { ...role, max_async: Number(role.max_async), timeout: Number(role.timeout) }
  }
  return result
}
export function validateLightRagRoles(roles: ConfigValues): string {
  const base = (roles.base ?? {}) as ConfigValues
  if (!base.profile_id || !base.model_id) return '请选择 LightRAG 基础模型'
  for (const key of Object.keys(roleNames)) {
    const role = (roles[key] ?? {}) as ConfigValues
    const selection = (role.selection ?? {}) as ConfigValues
    if (role.mode === 'model' && (!selection.profile_id || !selection.model_id)) return '请为独立角色选择正式模型'
    if (!Number.isInteger(Number(role.max_async)) || Number(role.max_async) < 1 || Number(role.max_async) > 32 || !Number.isInteger(Number(role.timeout)) || Number(role.timeout) < 1 || Number(role.timeout) > 3600) return '角色并发须为 1–32，超时须为 1–3600 秒的整数'
  }
  return ''
}
