import { Check, Plus, Search } from 'lucide-react'
import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { ModelEntry, ModelProfile } from '../../../types/modelSettings'
import { Field, inputClass, primaryClass, secondaryClass } from './Fields'

export interface WorkspaceModel {
  profile: ModelProfile
  model: ModelEntry
  connection: string
  provider: string
  isDefault: boolean
}

interface ModelWorkspaceProps {
  rows: WorkspaceModel[]
  selected: { profileId: string; modelId: string }
  adding: boolean
  disabled: boolean
  onAdd: () => void
  onSelect: (profile: ModelProfile, model: ModelEntry) => void
  compatibility: ReactNode
  children: ReactNode
}

/** 仅映射目录中的模型；编辑焦点不参与活动模型选择。 */
export function ModelWorkspace({
  rows,
  selected,
  adding,
  disabled,
  onAdd,
  onSelect,
  compatibility,
  children,
}: ModelWorkspaceProps) {
  const [query, setQuery] = useState('')
  const detailRef = useRef<HTMLDivElement>(null)
  const railRef = useRef<HTMLElement>(null)
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const visible = rows.filter(({ profile, model, connection, provider }) =>
    [
      model.name,
      model.model,
      profile.name,
      connection,
      provider,
      profile.binding,
    ].some((value) => value?.toLocaleLowerCase().includes(normalizedQuery)),
  )
  const revealDetail = () => {
    requestAnimationFrame(() => {
      const detail = detailRef.current
      const rail = railRef.current
      if (
        detail &&
        rail &&
        detail.getBoundingClientRect().top >
          rail.getBoundingClientRect().top + 24
      ) {
        detail.focus({ preventScroll: true })
        detail.scrollIntoView({ behavior: 'auto', block: 'start' })
      }
    })
  }
  return (
    <div className="@container/model-workspace min-w-0">
      <div className="grid min-w-0 items-start gap-5 @4xl/model-workspace:grid-cols-[minmax(14rem,18rem)_minmax(0,1fr)]">
        <aside
          ref={railRef}
          className="min-w-0 space-y-3"
          aria-label="模型列表"
        >
          <button
            type="button"
            className={`${primaryClass} flex w-full items-center justify-center gap-2`}
            disabled={disabled}
            aria-pressed={adding}
            onClick={() => {
              onAdd()
              revealDetail()
            }}
          >
            <Plus size={16} aria-hidden="true" />
            添加模型
          </button>
          <Field label="搜索模型或提供方">
            <span className="relative block">
              <Search
                size={16}
                aria-hidden="true"
                className="pointer-events-none absolute left-3 top-3 text-slate-400"
              />
              <input
                type="search"
                className={`${inputClass} pl-9!`}
                placeholder="模型、提供方或连接名称"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </span>
          </Field>
          <p className="text-xs text-slate-500" role="status">
            {normalizedQuery
              ? `找到 ${visible.length} / ${rows.length} 个模型`
              : `已配置 ${rows.length} 个模型`}
          </p>
          <div className="max-h-80 space-y-2 overflow-y-auto @4xl/model-workspace:max-h-[36rem]">
            {visible.map(
              ({ profile, model, connection, provider, isDefault }) => {
                const isSelected =
                  !adding &&
                  selected.profileId === profile.id &&
                  selected.modelId === model.id
                return (
                  <button
                    key={JSON.stringify([profile.id, model.id])}
                    type="button"
                    className={`w-full rounded-2xl border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-50 ${isSelected ? 'border-blue-400 bg-blue-50 ring-1 ring-blue-100' : 'border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/50'}`}
                    aria-pressed={isSelected}
                    disabled={disabled}
                    onClick={() => {
                      onSelect(profile, model)
                      revealDetail()
                    }}
                  >
                    <span className="flex flex-wrap items-start justify-between gap-2">
                      <span className="min-w-0 break-all text-sm font-semibold text-slate-800">
                        {model.name || model.model || '未填写模型'}
                      </span>
                      {isDefault && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                          <Check size={12} aria-hidden="true" />
                          草稿默认
                        </span>
                      )}
                    </span>
                    <span className="mt-1 block break-all text-xs leading-5 text-slate-500">
                      {connection} · {provider}
                    </span>
                    <span className="mt-1 block break-all text-xs text-slate-500">
                      {model.model || '模型标识待填写'}
                    </span>
                  </button>
                )
              },
            )}
            {!visible.length && (
              <div className="rounded-2xl border border-dashed border-slate-200 p-4 text-sm leading-6 text-slate-500">
                {rows.length
                  ? '没有匹配的模型，请修改搜索条件。'
                  : '尚未配置模型。点击“添加模型”，先选择已配置的提供方连接。'}
                {rows.length > 0 && (
                  <button
                    type="button"
                    className={`${secondaryClass} mt-3 block`}
                    onClick={() => setQuery('')}
                  >
                    清除搜索
                  </button>
                )}
              </div>
            )}
          </div>
          <p className="text-xs leading-5 text-slate-500">
            点击卡片仅切换编辑对象。默认模型需在详情中明确设置，应用草稿后正式生效。
          </p>
          <details className="rounded-xl border border-slate-200 bg-white p-3">
            <summary className="cursor-pointer text-sm font-medium text-slate-700 focus-visible:outline-blue-500">
              兼容配置（Profile）
            </summary>
            <div className="mt-3 space-y-3">{compatibility}</div>
          </details>
        </aside>
        <div
          ref={detailRef}
          tabIndex={-1}
          className="settings-card min-w-0 scroll-mt-6 rounded-2xl border border-slate-200 bg-white p-4 outline-none sm:p-5 focus-visible:ring-2 focus-visible:ring-blue-200"
          aria-label="模型添加与详情"
        >
          {children}
        </div>
      </div>
    </div>
  )
}
