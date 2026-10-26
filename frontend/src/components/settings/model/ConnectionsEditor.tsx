import { useState } from 'react'
import type {
  DiscoveredModel,
  ModelCatalog,
  ModelConnection,
  ProviderOption,
} from '../../../types/modelSettings'
import { newId, referencesTo } from './catalog'
import {
  ConnectionForm,
  Field,
  inputClass,
  ProviderSelect,
  secondaryClass,
} from './Fields'

interface ConnectionsEditorProps {
  catalog: ModelCatalog
  providers: ProviderOption[]
  discovery: { key: string; models: DiscoveredModel[] } | null
  onChange: (catalog: ModelCatalog) => void
  onError: (message: string) => void
  onInvalid: (invalid: boolean) => void
  onDiscover: (connection: ModelConnection) => void
  onSelect: () => void
  invalid: boolean
  busy: boolean
}
export function ConnectionsEditor({
  catalog,
  providers,
  discovery,
  onSelect,
  onChange,
  onError,
  onInvalid,
  onDiscover,
  invalid,
  busy,
}: ConnectionsEditorProps) {
  const connections = catalog.connections ?? []
  const [selectedId, setSelectedId] = useState(() =>
    connections.find((item) => discovery?.key === `connection/${item.id}`)?.id
      ?? connections[0]?.id ?? '',
  )
  const connection =
    connections.find((item) => item.id === selectedId) ?? connections[0]
  const patch = (change: Partial<ModelConnection>) =>
    onChange({
      ...catalog,
      connections: connections.map((item) =>
        item.id === connection?.id ? { ...item, ...change } : item,
      ),
    })
  return (
    <section className="settings-card space-y-5 rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-48 flex-1">
          <Field label="共享连接">
            <select
              className={inputClass}
              disabled={invalid}
              value={connection?.id ?? ''}
              onChange={(event) => { setSelectedId(event.target.value); onSelect() }}
            >
              <option value="" disabled>
                尚无连接
              </option>
              {connections.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name || item.provider}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <button
          type="button"
          className={secondaryClass}
          disabled={invalid}
          onClick={() => {
            const created: ModelConnection = {
              id: newId('connection'),
              name: '新共享连接',
              provider: 'openai',
              api_key: '',
              base_url: '',
              extra_headers: {},
            }
            onChange({ ...catalog, connections: [...connections, created] })
            setSelectedId(created.id)
          }}
        >
          新增连接
        </button>
      </div>
      <p className="text-sm text-slate-500">
        连接可被多个 Profile
        或其他服务引用。这里的修改也属于模型草稿，应用后才影响正式配置。
      </p>
      {connection ? (
        <div key={connection.id} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="连接名称">
              <input
                className={inputClass}
                value={connection.name || ''}
                onChange={(event) => patch({ name: event.target.value })}
              />
            </Field>
            <ProviderSelect
              value={connection.provider}
              options={providers}
              onChange={(provider) => patch({ provider })}
            />
          </div>
          <ConnectionForm
            fields={connection}
            options={providers.filter(
              (item) => item.value === connection.provider,
            )}
            onChange={patch}
            onInvalid={onInvalid}
          />
          <details className="rounded-xl border border-slate-200 p-3">
            <summary className="cursor-pointer text-sm font-medium text-slate-700">
              按用途覆盖地址和适配器
            </summary>
            <div className="mt-4 space-y-4">
              {(['llm', 'embedding'] as const).map((service) => {
                const override = connection.service_overrides?.[service] ?? {}
                const change = (fields: Record<string, unknown>) =>
                  patch({
                    service_overrides: {
                      ...connection.service_overrides,
                      [service]: { ...override, ...fields },
                    },
                  })
                return (
                  <div key={service} className="space-y-3">
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        checked={override.enabled === true}
                        onChange={(event) =>
                          change({ enabled: event.target.checked })
                        }
                      />
                      {service === 'llm'
                        ? '主语言／辅助任务模型覆盖'
                        : '嵌入模型覆盖'}
                    </label>
                    {override.enabled === true && (
                      <div className="grid gap-3 sm:grid-cols-2">
                        <Field label="适配器 binding（留空沿用 Profile）">
                          <input
                            className={inputClass}
                            value={String(override.binding || '')}
                            onChange={(event) =>
                              change({ binding: event.target.value })
                            }
                          />
                        </Field>
                        <Field label="专用 Base URL">
                          <input
                            className={inputClass}
                            value={String(override.base_url || '')}
                            onChange={(event) =>
                              change({ base_url: event.target.value })
                            }
                          />
                        </Field>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </details>
          <p className="text-xs leading-5 text-slate-500">
            模型发现只检查提供方模型列表接口，不能证明推理、嵌入或全部模型可用。后端不支持的发现方式会显示实际状态。
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={secondaryClass}
              disabled={busy || invalid}
              onClick={() => onDiscover(connection)}
            >
              模型发现（此连接）
            </button>
            <button
              type="button"
              className={`${secondaryClass} text-red-700`}
              disabled={invalid}
              onClick={() => {
                const refs = referencesTo(catalog, connection.id)
                if (refs.length) {
                  onError(
                    `连接仍被引用，请先解除或更换来源：${refs.join('、')}`,
                  )
                  return
                }
                if (
                  window.confirm(
                    '删除此共享连接？保存草稿并应用后才会影响正式目录。',
                  )
                ) {
                  onChange({
                    ...catalog,
                    connections: connections.filter(
                      (item) => item.id !== connection.id,
                    ),
                  })
                  setSelectedId('')
                }
              }}
            >
              删除连接
            </button>
          </div>
          {discovery?.key === `connection/${connection.id}` && (
            <div className="space-y-2 rounded-xl bg-blue-50 p-3" aria-label="共享连接发现结果">
              <p className="text-xs text-blue-800">
                此连接的发现结果（仅展示模型标识；未验证推理或嵌入能力）
              </p>
              {discovery.models.length ? (
                <ul className="max-h-48 space-y-1 overflow-y-auto text-sm text-slate-700">
                  {discovery.models.map((item) => (
                    <li key={item.id} className="break-all">
                      {item.id}{item.services?.length ? ` · ${item.services.join('/')}` : ''}
                    </li>
                  ))}
                </ul>
              ) : <p className="text-sm text-slate-500">此连接未返回模型标识。</p>}
            </div>
          )}
          <p className="break-all text-xs text-slate-500">
            引用：{referencesTo(catalog, connection.id).join('、') || '暂无'}
          </p>
        </div>
      ) : (
        <p className="text-sm text-slate-500">
          尚无共享连接。可以新增连接供各用途复用，也可在 Profile
          内维护独立连接。
        </p>
      )}
    </section>
  )
}
