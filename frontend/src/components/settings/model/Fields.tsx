import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import type {
  CatalogRecord,
  ConnectionFields,
  ProviderOption,
} from '../../../types/modelSettings'

export const inputClass =
  'settings-input w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50 disabled:text-slate-500'
export const secondaryClass =
  'settings-button-secondary min-h-10 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-50'
export const primaryClass =
  'settings-button min-h-10 rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-50'

export function Field({
  label,
  note,
  children,
}: {
  label: string
  note?: string
  children: ReactNode
}) {
  return (
    <label className="settings-label flex min-w-0 flex-col gap-1.5 text-sm font-medium text-slate-700">
      <span>{label}</span>
      {children}
      {note && (
        <span className="text-xs font-normal leading-5 text-slate-500">
          {note}
        </span>
      )}
    </label>
  )
}

export function JsonField({
  value,
  onChange,
  label,
  validate,
  onInvalid,
}: {
  value: unknown
  onChange: (value: CatalogRecord) => void
  label: string
  validate?: (value: CatalogRecord) => boolean
  onInvalid: (invalid: boolean) => void
}) {
  const [text, setText] = useState(() =>
    typeof value === 'string' ? value : JSON.stringify(value ?? {}, null, 2),
  )
  const [error, setError] = useState('')
  const id = useId()
  return (
    <Field label={label} note="JSON 对象；未修改的 *** 按原标识保留服务端值。">
      <textarea
        className={inputClass}
        rows={3}
        value={text}
        aria-invalid={!!error}
        aria-describedby={error ? id : undefined}
        spellCheck={false}
        autoComplete="off"
        onChange={(event) => {
          const next = event.target.value
          setText(next)
          try {
            const parsed: unknown = JSON.parse(next)
            if (
              !parsed ||
              typeof parsed !== 'object' ||
              Array.isArray(parsed) ||
              (validate && !validate(parsed as CatalogRecord))
            )
              throw new Error('invalid')
            setError('')
            onInvalid(false)
            onChange(parsed as CatalogRecord)
          } catch {
            setError('请输入有效的 JSON 对象；请求头的值必须是文本')
            onInvalid(true)
          }
        }}
      />
      {error && (
        <span id={id} role="alert" className="text-xs text-red-700">
          {error}
        </span>
      )}
    </Field>
  )
}

export function ProviderSelect({
  value,
  options,
  onChange,
}: {
  value: string
  options: ProviderOption[]
  onChange: (value: string) => void
}) {
  return (
    <Field label="提供方">
      <select
        className={inputClass}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">请选择提供方</option>
        {!options.some((option) => option.value === value) && value && (
          <option value={value}>{value}（现有配置）</option>
        )}
        {options
          .filter(
            (option) => option.status !== 'legacy' || option.value === value,
          )
          .map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
      </select>
    </Field>
  )
}

export function ConnectionForm({
  fields,
  onChange,
  options,
  onInvalid,
}: {
  fields: ConnectionFields
  onChange: (patch: Partial<ConnectionFields>) => void
  options: ProviderOption[]
  onInvalid: (invalid: boolean) => void
}) {
  const [replaceKey, setReplaceKey] = useState(false)
  const isMasked =
    fields.api_key === '***' ||
    (Array.isArray(fields.api_key) &&
      fields.api_key.length > 0 &&
      fields.api_key.every((value) => value === '***'))
  const formats = [
    ...new Set([
      'auto',
      ...options.flatMap((option) => option.api_formats ?? []),
      fields.api_format || 'auto',
    ]),
  ]
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="服务地址（Base URL）">
        <input
          className={inputClass}
          value={fields.base_url || ''}
          placeholder="使用提供方要求的接口地址"
          onChange={(event) => onChange({ base_url: event.target.value })}
        />
      </Field>
      <Field label="API 协议">
        <select
          className={inputClass}
          value={fields.api_format || 'auto'}
          onChange={(event) => onChange({ api_format: event.target.value })}
        >
          {formats.map((format) => (
            <option key={format} value={format}>
              {format}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="API Key"
        note={
          isMasked && !replaceKey
            ? '已保存且脱敏。保持不动会保留原凭据；点击更换后输入新值；清除需点击明确清除按钮。'
            : '仅用于提交，不写入浏览器长期缓存。输入新值将替换原凭据。'
        }
      >
        {isMasked && !replaceKey ? (
          <button
            type="button"
            className={`${secondaryClass} text-left`}
            aria-label="更换凭据（API Key）"
            onClick={() => setReplaceKey(true)}
          >
            ••••••••　更换凭据
          </button>
        ) : (
          <input
            className={inputClass}
            type="password"
            autoComplete="new-password"
            value={
              isMasked
                ? ''
                : Array.isArray(fields.api_key)
                  ? fields.api_key.join('\n')
                  : fields.api_key || ''
            }
            onChange={(event) => onChange({ api_key: event.target.value })}
          />
        )}
        {replaceKey && isMasked && (
          <button
            type="button"
            className={secondaryClass}
            aria-label="明确清除已保存凭据（API Key）"
            onClick={() => onChange({ api_key: '' })}
          >
            明确清除已保存凭据
          </button>
        )}
        {Array.isArray(fields.api_key) && (
          <span className="text-xs text-slate-500">
            当前为 Key 池；未改动时保留整组，输入新值将替换整组。
          </span>
        )}
      </Field>
      <Field label="API Version">
        <input
          className={inputClass}
          value={fields.api_version || ''}
          onChange={(event) => onChange({ api_version: event.target.value })}
        />
      </Field>
      <Field
        label="应用 ID（App ID，可选）"
        note="按提供方要求填写；模型发现不验证此字段。"
      >
        <input
          className={inputClass}
          value={fields.app_id || ''}
          onChange={(event) => onChange({ app_id: event.target.value })}
          autoComplete="off"
        />
      </Field>
      <Field label="代理（Proxy）" note="是否生效取决于提供方适配器。">
        <input
          className={inputClass}
          value={fields.proxy || ''}
          onChange={(event) => onChange({ proxy: event.target.value })}
        />
      </Field>
      <JsonField
        label="额外请求头（Extra Headers）"
        value={fields.extra_headers}
        onChange={(headers) =>
          onChange({ extra_headers: headers as Record<string, string> })
        }
        validate={(headers) =>
          Object.values(headers).every((value) => typeof value === 'string')
        }
        onInvalid={onInvalid}
      />
    </div>
  )
}
