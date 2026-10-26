import { useEffect, useRef, useState } from 'react'
import {
  applyModelDraft,
  discardModelDraft,
  discoverProviderModels,
  fetchLanguageModels,
  readModelSettings,
  saveModelDraft,
} from '../../api/modelSettings'
import type {
  DiscoveredModel,
  ModelCatalog,
  ModelDraft,
  ModelProfile,
  ModelServiceName,
  ProviderOption,
  ProviderProbeRequest,
} from '../../types/modelSettings'
import {
  connectionPayload,
  embeddingIdentityChanged,
  equal,
  probePayload,
  safeError,
  serviceLabels,
  validateCatalog,
} from './model/catalog'
import { ConnectionsEditor } from './model/ConnectionsEditor'
import { primaryClass, secondaryClass } from './model/Fields'
import { ServiceEditor } from './model/ServiceEditor'

interface ModelSettingsProps {
  onDirtyChange?: (dirty: boolean) => void
}
type Tab = ModelServiceName | 'connections'
interface Snapshot {
  live: ModelCatalog
  draft: ModelDraft | null
  baseline: ModelCatalog
  providers: Record<string, ProviderOption[]>
}

export function ModelSettings({ onDirtyChange }: ModelSettingsProps) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null)
  const [tab, setTab] = useState<Tab>('llm')
  const [busy, setBusy] = useState('读取模型设置')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [invalid, setInvalid] = useState(false)
  const [revision, setRevision] = useState(0)
  const [discovery, setDiscovery] = useState<{
    key: string
    models: DiscoveredModel[]
  } | null>(null)
  const lock = useRef(false)
  const mounted = useRef(true)
  const readVersion = useRef(0)
  const dirty =
    !!catalog && !!snapshot && (!equal(catalog, snapshot.baseline) || invalid)

  useEffect(() => {
    onDirtyChange?.(dirty)
  }, [dirty, onDirtyChange])
  useEffect(
    () => () => {
      onDirtyChange?.(false)
    },
    [onDirtyChange],
  )

  function accept(data: Awaited<ReturnType<typeof readModelSettings>>) {
    const baseline = data.draft?.catalog ?? data.catalog
    setSnapshot({
      live: data.catalog,
      draft: data.draft,
      baseline,
      providers: data.providers,
    })
    setCatalog(baseline)
    setInvalid(false)
    setRevision((value) => value + 1)
    setDiscovery(null)
  }
  async function load() {
    const version = ++readVersion.current
    setBusy('读取模型设置')
    setError('')
    try {
      const data = await readModelSettings()
      if (mounted.current && version === readVersion.current) accept(data)
    } catch (cause) {
      if (mounted.current && version === readVersion.current)
        setError(safeError(cause))
    } finally {
      if (mounted.current && version === readVersion.current) setBusy('')
    }
  }
  useEffect(() => {
    mounted.current = true
    void load()
    return () => {
      mounted.current = false
      readVersion.current += 1
    }
  }, [])

  function edit(next: ModelCatalog) {
    setCatalog(next)
    setNotice('')
    setError('')
    setDiscovery(null)
  }

  async function perform(label: string, action: () => Promise<void>) {
    if (lock.current) return
    lock.current = true
    setBusy(label)
    setError('')
    setNotice('')
    setDiscovery(null)
    try {
      await action()
    } catch (cause) {
      setError(safeError(cause, catalog ?? undefined))
    } finally {
      lock.current = false
      setBusy('')
    }
  }

  async function save() {
    if (!catalog || !snapshot || invalid) return
    const validation = validateCatalog(catalog)
    if (validation) {
      setError(validation)
      return
    }
    await perform('保存草稿', async () => {
      const { draft } = await saveModelDraft(catalog, snapshot.draft)
      if (!draft?.catalog) throw new Error('服务端未返回有效目录草稿，请重试')
      setSnapshot({ ...snapshot, draft, baseline: draft.catalog })
      setCatalog(draft.catalog)
      setRevision((value) => value + 1)
      setNotice('草稿已保存；正式配置尚未改变。')
    })
  }

  async function apply() {
    if (!catalog || !snapshot?.draft?.catalog || dirty) return
    if (
      embeddingIdentityChanged(snapshot.live, catalog) &&
      !window.confirm(
        '嵌入模型的身份属性被修改或删除；若已有知识库绑定这些模型，可能需要重建或暂时不可用；无法完全确定受影响范围。此处不会自动重建。确认应用已保存草稿？',
      )
    )
      return
    await perform('应用已保存草稿', async () => {
      try {
        const applied = await applyModelDraft()
        const data = await readModelSettings()
        if (data.draft !== null)
          throw new Error('应用后仍存在草稿，可能有并发修改；请核对真实状态')
        if (!equal(data.catalog, applied.catalog))
          throw new Error('正式目录已发生并发变化，请重新读取并核对')
        accept(data)
        setNotice('已核实正式目录更新且草稿已清空；后续调用使用正式配置。')
      } catch (cause) {
        // 应用可能已发生部分副作用；读取事实但保留编辑，不能声称回滚。
        try {
          const data = await readModelSettings()
          setSnapshot((current) =>
            current
              ? { ...current, live: data.catalog, draft: data.draft }
              : current,
          )
        } catch {
          /* 原错误在外层展示，同时明确正式状态未确认。 */
        }
        throw new Error(
          `${safeError(cause, catalog)}。当前编辑已保留，正式状态可能已有变化；请核对后重试或重新读取。`,
        )
      }
    })
  }

  async function discard() {
    if (!snapshot || (!snapshot.draft && !dirty)) return
    if (
      !window.confirm(
        '丢弃已存草稿和当前未保存编辑？此操作不删除正式目录及正式凭据。',
      )
    )
      return
    await perform('丢弃草稿', async () => {
      if (snapshot.draft) await discardModelDraft()
      const data = await readModelSettings()
      accept(data)
      setNotice(
        snapshot.draft
          ? data.draft
            ? '发现新的服务端草稿，已重新读取，请核对。'
            : '草稿已丢弃，已重新读取正式配置。'
          : '已撤销本地编辑，已重新读取服务端状态。',
      )
    })
  }

  function canFetch(profile: ModelProfile) {
    if (
      !catalog ||
      !snapshot ||
      tab === 'embedding' ||
      tab === 'connections' ||
      profile.provider_ref
    )
      return false
    const payload = probePayload(catalog, tab, profile)
    // fetch-models 不支持 header/version/proxy/keypool；掩码可能来自草稿而非正式目录。
    const formalProfile = snapshot.live.services[tab]?.profiles.find(
      (item) => item.id === profile.id,
    )
    const formalMask =
      payload.api_key !== '***' ||
      (!snapshot.draft?.catalog &&
        !!formalProfile &&
        formalProfile.api_key === '***' &&
        formalProfile.connection_id === profile.connection_id)
    return (
      typeof payload.api_key !== 'object' &&
      formalMask &&
      !payload.api_version &&
      !payload.proxy &&
      (!payload.extra_headers ||
        (typeof payload.extra_headers === 'object' &&
          !Object.keys(payload.extra_headers).length))
    )
  }

  async function discover(
    payload: ProviderProbeRequest,
    key: string,
    useFetch = false,
  ) {
    await perform('发现模型', async () => {
      const result = useFetch
        ? {
            ...(await fetchLanguageModels(payload)),
            status: 'connected',
            warning: undefined,
          }
        : await discoverProviderModels(payload)
      const messages: Record<string, string> = {
        unauthorized: '凭据无效或权限不足',
        forbidden: '服务拒绝访问',
        rate_limited: '请求限流',
        timeout: '发现超时',
        unreachable: '无法连接服务',
        unavailable: '服务未提供可用模型发现接口',
        unsupported: '此提供方不支持该发现方式',
      }
      if (result.status !== 'connected')
        throw new Error(
          `模型发现未成功：${messages[result.status] || result.status}。未执行推理或嵌入。`,
        )
      setDiscovery({ key, models: result.models ?? [] })
      setNotice(
        `模型列表接口已响应，共发现 ${result.models?.length ?? 0} 个标识${result.warning ? '（结果可能不完整）' : ''}；未验证推理或嵌入能力。`,
      )
    })
  }

  if (!snapshot || !catalog)
    return (
      <section
        className="rounded-2xl border border-slate-200 bg-white p-6"
        aria-busy={!!busy}
      >
        {busy ? (
          <p role="status">正在读取模型设置…</p>
        ) : (
          <>
            <p role="alert" className="settings-error text-sm text-red-700">
              {error || '模型设置读取失败'}
            </p>
            <button
              type="button"
              className={`${secondaryClass} mt-4`}
              onClick={() => void load()}
            >
              重试读取
            </button>
          </>
        )}
      </section>
    )
  const embeddingRisk = embeddingIdentityChanged(snapshot.live, catalog)
  const embeddingDefaultChanged = !equal(
    [
      snapshot.live.services.embedding?.active_profile_id,
      snapshot.live.services.embedding?.active_model_id,
    ],
    [
      catalog.services.embedding?.active_profile_id,
      catalog.services.embedding?.active_model_id,
    ],
  )
  return (
    <section
      className="space-y-5"
      aria-label="模型与服务设置"
      aria-busy={!!busy}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-slate-900">模型与服务</h2>
          <p className="mt-1 text-sm text-slate-500">
            配置连接、模型和活动选择，先保存草稿，再应用更改。
          </p>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs font-medium ${dirty ? 'bg-amber-50 text-amber-800' : snapshot.draft?.catalog ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-600'}`}
        >
          {dirty
            ? '有未保存编辑'
            : snapshot.draft?.catalog
              ? '已保存草稿 · 尚未生效'
              : '正式配置'}
        </span>
      </div>
      {snapshot.draft?.updated_at && (
        <p className="text-xs text-slate-500">
          草稿保存时间：{snapshot.draft.updated_at}
        </p>
      )}
      {snapshot.draft && Object.keys(snapshot.draft.extensions).length > 0 && (
        <p className="settings-note text-sm text-blue-700">
          草稿包含其他页面状态；保存时保留。应用只处理模型目录，并清空整份草稿；丢弃也会移除整份草稿。
        </p>
      )}
      <div
        className="flex flex-wrap gap-2"
        role="tablist"
        aria-label="模型设置子页"
      >
        {(
          [
            ...Object.entries(serviceLabels),
            ['connections', '提供方与连接'],
          ] as [Tab, string][]
        ).map(([value, label]) => (
          <button
            type="button"
            role="tab"
            aria-selected={tab === value}
            aria-controls="model-settings-panel"
            id={`model-tab-${value}`}
            key={value}
            disabled={!!busy}
            className={`${secondaryClass} ${tab === value ? 'border-blue-300 bg-blue-50 text-blue-700' : ''}`}
            onClick={() => {
              if (value === tab) return
              if (invalid) {
                setError(
                  '请先修正 JSON 格式，再切换子页；其他未保存字段仍保留。',
                )
                return
              }
              if (
                dirty &&
                !window.confirm(
                  '当前目录有未保存编辑。继续切换子页并保留全部编辑？',
                )
              )
                return
              setTab(value)
              setError('')
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {error && (
        <div
          role="alert"
          className="settings-error rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      )}
      {notice && (
        <p
          role="status"
          className="rounded-xl border border-blue-100 bg-blue-50 p-3 text-sm text-blue-800"
        >
          {notice}
        </p>
      )}
      {(embeddingRisk || embeddingDefaultChanged) && (
        <div className="settings-note rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900">
          {embeddingRisk
            ? '嵌入模型的名称标识、维度、端点等身份属性被修改或删除；若已有知识库绑定这些模型，可能需要重建或不可用。受影响范围无法完全确定，应用时需确认。'
            : '切换默认嵌入模型不会遍历重建旧库；已有库可能继续使用原绑定。'}
          重建需到知识库页面操作，此页不会自动重建。仅更换 API Key
          不改变嵌入身份。
        </div>
      )}
      <fieldset
        disabled={!!busy}
        className="min-w-0 disabled:opacity-70"
        id="model-settings-panel"
        role="tabpanel"
        aria-labelledby={`model-tab-${tab}`}
      >
        {tab === 'connections' ? (
          <ConnectionsEditor
            key={`${tab}/${revision}`}
            catalog={catalog}
            providers={[
              ...(snapshot.providers.llm ?? []),
              ...(snapshot.providers.embedding ?? []).filter(
                (item) =>
                  !snapshot.providers.llm?.some(
                    (option) => option.value === item.value,
                  ),
              ),
            ]}
            discovery={discovery}
            onSelect={() => { setDiscovery(null); setNotice('') }}
            onChange={edit}
            onError={setError}
            onInvalid={setInvalid}
            onDiscover={(connection) =>
              void discover(
                connectionPayload(connection),
                `connection/${connection.id}`,
              )
            }
            invalid={invalid}
            busy={!!busy}
          />
        ) : (
          <ServiceEditor
            key={`${tab}/${revision}`}
            catalog={catalog}
            live={snapshot.live}
            name={tab}
            providers={snapshot.providers[tab] ?? []}
            onChange={edit}
            onError={setError}
            onInvalid={setInvalid}
            invalid={invalid}
            busy={!!busy}
            canFetch={canFetch}
            discovery={discovery}
            onDiscover={(profile, useFetch) =>
              void discover(
                probePayload(catalog, tab, profile),
                `${tab}/${profile.id}`,
                useFetch,
              )
            }
          />
        )}
      </fieldset>
      <div className="settings-card flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4">
        <button
          type="button"
          className={primaryClass}
          disabled={!!busy || !dirty || invalid}
          onClick={() => void save()}
        >
          保存草稿
        </button>
        <button
          type="button"
          className={primaryClass}
          disabled={!!busy || dirty || !snapshot.draft?.catalog}
          onClick={() => void apply()}
        >
          应用更改
        </button>
        <button
          type="button"
          className={secondaryClass}
          disabled={!!busy || (!dirty && !snapshot.draft)}
          onClick={() => void discard()}
        >
          {snapshot.draft ? '丢弃草稿' : '撤销本地编辑'}
        </button>
        <button
          type="button"
          className={secondaryClass}
          disabled={!!busy}
          onClick={() => {
            if (
              !dirty ||
              window.confirm('重新读取会替换当前未保存编辑，是否继续？')
            )
              void load()
          }}
        >
          重新读取
        </button>
        <p className="text-xs text-slate-500" role="status">
          {busy
            ? `${busy}中…`
            : dirty
              ? '请先保存当前编辑，再应用已存草稿。'
              : snapshot.draft?.catalog
                ? '应用只使用已保存草稿，不包含其他设置区域。'
                : '当前无可应用的目录草稿。'}
        </p>
      </div>
    </section>
  )
}
