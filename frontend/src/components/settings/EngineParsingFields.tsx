import { useEffect, useId, useRef, useState } from 'react'
import type { CheckResult, ConfigValues } from '../../types/engineSettings'

export interface SettingsField {
  key: string
  label: string
  kind?: 'text' | 'number' | 'checkbox' | 'select' | 'secret' | 'url'
  options?: readonly string[]
  min?: number
  max?: number
  required?: boolean
  note?: string
}
export const numberField = (key: string, label: string, min: number, max: number): SettingsField => ({ key, label, kind: 'number', min, max })
export const selectField = (key: string, label: string, options: readonly string[]): SettingsField => ({ key, label, kind: 'select', options })
export const toggleField = (key: string, label: string): SettingsField => ({ key, label, kind: 'checkbox' })
export const secretField = (key: string, label: string): SettingsField => ({ key, label, kind: 'secret' })
export const urlField = (key: string, label: string): SettingsField => ({ key, label, kind: 'url', required: true })

export function useSettingsDirty(dirty: boolean, onDirtyChange?: (dirty: boolean) => void) {
  const callback = useRef(onDirtyChange)
  callback.current = onDirtyChange
  useEffect(() => { callback.current?.(dirty) }, [dirty])
  useEffect(() => () => { callback.current?.(false) }, [])
  useEffect(() => {
    if (!dirty) return
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [dirty])
}
export function mayLeaveSettings(dirty: boolean) { return !dirty || window.confirm('当前有未保存修改，放弃修改并切换？') }
export function settingsError(error: unknown) { return error instanceof Error ? error.message : '请求失败，请重试' }

export function validateSettings(fields: readonly SettingsField[], values: ConfigValues): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const field of fields) {
    const value = values[field.key]
    if (field.kind === 'number') {
      const number = Number(value)
      if (value === '' || value == null || !Number.isInteger(number) || number < (field.min ?? -Infinity) || number > (field.max ?? Infinity)) errors[field.key] = `请输入 ${field.min}–${field.max} 之间的整数`
    } else if (field.required && !String(value ?? '').trim()) errors[field.key] = '请填写此项'
    if (field.kind === 'url' && value) {
      try { if (!['http:', 'https:'].includes(new URL(String(value)).protocol)) errors[field.key] = '请输入 http 或 https 地址' }
      catch { errors[field.key] = '请输入完整的 http 或 https 地址' }
    }
  }
  return errors
}
export function settingsPayload(fields: readonly SettingsField[], values: ConfigValues): ConfigValues {
  const payload: ConfigValues = {}
  for (const field of fields) {
    const value = values[field.key]
    if (value !== undefined) payload[field.key] = field.kind === 'number' ? Number(value) : value
  }
  return payload
}

function SecretInput({ id, value, onChange }: { id: string; value: ConfigValues[string]; onChange: (value: string | undefined) => void }) {
  const [intent, setIntent] = useState('keep')
  return <div className="space-y-2">
    <select id={`${id}-action`} aria-label="凭据操作" className="settings-input" value={intent} onChange={event => {
      const next = event.target.value
      setIntent(next)
      onChange(next === 'clear' ? '' : undefined)
    }}>
      <option value="keep">保留已保存凭据</option><option value="replace">替换凭据</option><option value="clear">清除已保存凭据</option>
    </select>
    <input id={id} className="settings-input" type="password" autoComplete="new-password" disabled={intent !== 'replace'} value={typeof value === 'string' ? value : ''} placeholder={intent === 'keep' ? '不回显凭据；保存时保留' : '输入新的凭据'} onChange={event => onChange(event.target.value || undefined)} />
    {intent === 'clear' && <p className="settings-note">保存后将清除凭据。</p>}
    {intent === 'replace' && !value && <p className="settings-note">留空保留原凭据；输入新值后替换。</p>}
  </div>
}

export function EngineParsingFields({ fields, values, onChange, errors = {}, disabled = false }: {
  fields: readonly SettingsField[]; values: ConfigValues; onChange: (key: string, value: ConfigValues[string]) => void; errors?: Record<string, string>; disabled?: boolean
}) {
  const prefix = useId()
  return <fieldset disabled={disabled} className="grid min-w-0 gap-4 sm:grid-cols-2">
    {fields.map(field => {
      const id = `${prefix}-${field.key}`
      const value = values[field.key]
      return <div key={field.key} className="min-w-0 space-y-1.5">
        <label htmlFor={id} className="settings-label">{field.label}</label>
        {field.kind === 'secret' ? <SecretInput id={id} value={value} onChange={next => onChange(field.key, next)} />
          : field.kind === 'checkbox' ? <input id={id} type="checkbox" checked={Boolean(value)} onChange={event => onChange(field.key, event.target.checked)} className="h-5 w-5 accent-blue-600" />
          : field.kind === 'select' ? <select id={id} className="settings-input" value={String(value ?? '')} onChange={event => onChange(field.key, event.target.value)}>
            {!field.options?.includes(String(value ?? '')) && <option value={String(value ?? '')}>{String(value ?? '请选择')}</option>}
            {field.options?.map(option => <option key={option} value={option}>{option}</option>)}
          </select>
          : <input id={id} className="settings-input" type={field.kind === 'number' ? 'number' : field.kind === 'url' ? 'url' : 'text'} min={field.min} max={field.max} step={field.kind === 'number' ? 1 : undefined} value={typeof value === 'string' || typeof value === 'number' ? value : ''} aria-invalid={Boolean(errors[field.key])} aria-describedby={errors[field.key] ? `${id}-error` : undefined} onChange={event => onChange(field.key, event.target.value)} />}
        {field.note && <p className="settings-note">{field.note}</p>}
        {errors[field.key] && <p id={`${id}-error`} className="settings-error" role="alert">{errors[field.key]}</p>}
      </div>
    })}
  </fieldset>
}
export function SettingsCheckResult({ result }: { result: CheckResult | null }) {
  if (!result) return null
  return <div className={result.ok ? 'rounded-xl border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900' : 'settings-error'} role="status">
    <p>{result.ok ? '本次检查通过' : '本次检查未通过'}{result.message ? `：${result.message}` : ''}{result.title ? ` · ${result.title}` : ''}</p>
    {result.error && <p>{result.error}</p>}
    {result.reachable !== undefined && <p>连接：{result.reachable ? '可达' : '未证实可达'}；凭据：{result.credentials_ok ? '通过' : '未通过'}；远端知识库：{result.knowledge_base_found ? result.knowledge_base_name || '已找到' : '未找到'}</p>}
    {result.detail && <p>{result.detail}</p>}
    {result.checks && <ul className="mt-2 space-y-2">{result.checks.map(check => <li key={check.key}>{check.ok ? '通过' : check.optional ? '可选项未满足' : '未通过'} · {check.label}{check.detail ? `：${check.detail}` : ''}</li>)}</ul>}
  </div>
}
