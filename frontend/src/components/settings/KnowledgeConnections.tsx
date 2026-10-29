import { Database, Plus, RefreshCw, Settings2 } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { settingsRequest } from '../../api/settingsHttp'
import { useApp } from '../../store/AppContext'

interface KnowledgeBase {
  id?: string | null
  name: string
  status?: string | null
  available?: boolean
  read_only?: boolean
  assigned?: boolean
  source?: string | null
  metadata?: {
    rag_provider?: string
    type?: string
    needs_reindex?: boolean
    last_error?: string
  } | null
}

interface RagProvider {
  id: string
  name: string
  configured: boolean
  readiness_reason?: string
}

interface EmbeddingOption {
  profile_id: string
  profile_name: string
  model_id: string
  label: string
  detail?: string
}

interface EmbeddingModels {
  embedding: {
    active: { profile_id?: string | null; model_id?: string | null }
    options: EmbeddingOption[]
  }
}

interface KnowledgeConfig {
  kb_name: string
  config: { rag_provider?: string; type?: string; read_only?: boolean; source?: string }
}

interface BindingEditor {
  kb: KnowledgeBase
  currentProvider: string
  selectedProvider: string
  canEdit: boolean
  loading: boolean
  error: string
}
interface CreationTask {
  name: string
  task_id: string
}

type Resource = 'knowledge' | 'providers' | 'embedding'

const DEFAULT_ENGINE = 'llamaindex'
// 通用 POST 的已核实路径；未知目录项必须先核实能力，避免后端回退成默认引擎。
const CREATE_ENGINES = new Set(['llamaindex', 'pageindex', 'pageindex-oss', 'graphrag', 'lightrag'])
const EMBEDDING_ENGINES = new Set(['llamaindex', 'graphrag', 'lightrag'])
const CONNECT_NOTES: Record<string, string> = {
  weknora: 'WeKnora 需要专用连接流程注册远端知识库；这里仅提供引擎配置入口。',
  ima: 'IMA 需要专用连接流程关联已有远端知识库，文件上传在 IMA 中完成。',
  'lightrag-server': 'LightRAG Server 需要专用连接流程关联服务器与远端知识库。',
  kiwix: 'Kiwix 需要专用连接流程关联已有 ZIM 资源。',
}
const STATUS_LABELS: Record<string, string> = {
  initializing: '初始化中', processing: '处理中', indexing: '索引中',
  ready: '就绪', error: '失败', needs_reindex: '需要重建索引',
  unavailable: '不可用', unknown: '状态未知',
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '请求失败，请重试'
}

function embeddingValue(option: Pick<EmbeddingOption, 'profile_id' | 'model_id'>): string {
  return JSON.stringify({ profile_id: option.profile_id, model_id: option.model_id })
}

function bindingRestriction(kb: KnowledgeBase): string {
  if (kb.read_only || kb.assigned) return '只读或共享知识库不能在此变更绑定'
  if (kb.available === false) return '知识库当前不可用，不能变更绑定'
  if (kb.source && kb.source !== 'user' && kb.source !== 'admin') return '远端或未知来源的知识库不能在此变更绑定'
  if (kb.metadata?.type || !CREATE_ENGINES.has(kb.metadata?.rag_provider ?? '')) return '连接型或未核实本地能力的知识库不能在此变更绑定'
  return ''
}

// 此路由直接按名称索引配置；列表 id 可能带 admin:kb: 前缀，不能用于此路由。
function knowledgeConfigPath(kb: KnowledgeBase): string {
  return `/api/knowledge-bases/${encodeURIComponent(kb.name)}/config`
}
/** BankTab 顶部的真实知识库入口；绑定变更仅在用户明确确认后提交。 */
export function KnowledgeConnections() {
  const { openEngineSettings, refreshKnowledgeBases, setHasUnsavedChanges } = useApp()
  const formId = useId()
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([])
  const [providers, setProviders] = useState<RagProvider[]>([])
  const [models, setModels] = useState<EmbeddingModels['embedding'] | null>(null)
  const [resourceErrors, setResourceErrors] = useState<Partial<Record<Resource, string>>>({})
  const [loading, setLoading] = useState(true)
  const [formOpen, setFormOpen] = useState(false)
  const [name, setName] = useState('')
  const [engine, setEngine] = useState(DEFAULT_ENGINE)
  const [embedding, setEmbedding] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [submitted, setSubmitted] = useState<CreationTask | null>(null)
  const [refreshError, setRefreshError] = useState('')
  const [binding, setBinding] = useState<BindingEditor | null>(null)
  const [bindingSaving, setBindingSaving] = useState(false)
  const [bindingNotice, setBindingNotice] = useState('')
  const bindingRequest = useRef<AbortController | null>(null)
  const bindingSavingRef = useRef(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const request = useRef<AbortController | null>(null)
  const mounted = useRef(false)
  const submittingRef = useRef(false)
  const bindingDirty = !!binding && binding.selectedProvider !== binding.currentProvider
  const dirty = name !== '' || engine !== DEFAULT_ENGINE || embedding !== '' || files.length > 0 || submitting || bindingDirty || bindingSaving
  const busy = submitting || bindingSaving || !!binding?.loading
  const selectedProvider = providers.find((provider) => provider.id === engine)
  const canCreate = !!selectedProvider && CREATE_ENGINES.has(engine)
  const usesEmbedding = EMBEDDING_ENGINES.has(engine)
  const activeModel = models?.options.find((option) => (
    option.profile_id === models.active.profile_id && option.model_id === models.active.model_id
  ))

  const reload = useCallback(async () => {
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    setLoading(true)
    const { signal } = controller
    const [knowledgeResult, providerResult, modelResult] = await Promise.allSettled([
      settingsRequest<KnowledgeBase[]>('/api/knowledge-bases', { signal }),
      settingsRequest<{ providers: RagProvider[] }>('/api/knowledge-bases/rag-providers', { signal }),
      settingsRequest<EmbeddingModels>('/api/knowledge-bases/rag-pipelines/model-options?kinds=embedding', { signal }),
    ])
    if (signal.aborted || !mounted.current) return
    const errors: Partial<Record<Resource, string>> = {}
    if (knowledgeResult.status === 'fulfilled') setKnowledgeBases(knowledgeResult.value)
    else errors.knowledge = errorMessage(knowledgeResult.reason)
    if (providerResult.status === 'fulfilled') setProviders(providerResult.value.providers)
    else errors.providers = errorMessage(providerResult.reason)
    if (modelResult.status === 'fulfilled') setModels(modelResult.value.embedding)
    else {
      setModels(null)
      errors.embedding = errorMessage(modelResult.reason)
    }
    setResourceErrors(errors)
    setLoading(false)
  }, [])

  useEffect(() => {
    mounted.current = true
    void reload()
    return () => {
      mounted.current = false
      request.current?.abort()
      bindingRequest.current?.abort()
    }
  }, [reload])

  useEffect(() => {
    setHasUnsavedChanges(dirty)
  }, [dirty, setHasUnsavedChanges])

  useEffect(() => () => setHasUnsavedChanges(false), [setHasUnsavedChanges])

  useEffect(() => {
    if (!dirty) return
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [dirty])

  async function refreshLists(taskSubmitted = false) {
    setRefreshError('')
    const [, sharedResult] = await Promise.allSettled([reload(), refreshKnowledgeBases()])
    if (mounted.current && sharedResult.status === 'rejected') {
      setRefreshError(`${taskSubmitted ? '建库任务已提交，但' : ''}应用知识库列表刷新失败：${errorMessage(sharedResult.reason)}。${taskSubmitted ? '请勿重复提交。' : '请刷新重试。'}`)
    }
  }

  function resetForm() {
    setName('')
    setEngine(DEFAULT_ENGINE)
    setEmbedding('')
    setFiles([])
    if (fileInput.current) fileInput.current.value = ''
    setHasUnsavedChanges(false)
  }

  function closeForm() {
    if (submittingRef.current) return
    if (dirty && !window.confirm('有未提交的建库信息，确定关闭并放弃这些更改？')) return
    resetForm()
    setSubmitError('')
    setFormOpen(false)
  }

  function openCreation() {
    if (busy) return
    if (bindingDirty && !window.confirm('有未提交的引擎绑定更改，确定放弃并切换到新建知识库？')) return
    setBinding(null)
    setFormOpen(true)
  }

  async function openBinding(kb: KnowledgeBase) {
    if (busy || bindingRestriction(kb)) return
    if (dirty && !window.confirm('有未提交的更改，确定放弃并读取此知识库的引擎绑定？')) return
    resetForm()
    setFormOpen(false)
    setSubmitError('')
    bindingRequest.current?.abort()
    const controller = new AbortController()
    bindingRequest.current = controller
    setBinding({ kb, currentProvider: '', selectedProvider: '', canEdit: false, loading: true, error: '' })
    try {
      const { config } = await settingsRequest<KnowledgeConfig>(knowledgeConfigPath(kb), { signal: controller.signal })
      if (controller.signal.aborted || !mounted.current) return
      const currentProvider = config.rag_provider ?? ''
      const restriction = config.read_only || config.type || (config.source && config.source !== 'user' && config.source !== 'admin')
      if (restriction || !CREATE_ENGINES.has(currentProvider)) {
        setBinding({ kb, currentProvider, selectedProvider: currentProvider, canEdit: false, loading: false, error: '最新配置不是可在此变更绑定的本地普通知识库，请沿用其专用工作流。' })
        return
      }
      setBinding({ kb, currentProvider, selectedProvider: currentProvider, canEdit: true, loading: false, error: '' })
    } catch (error) {
      if (!controller.signal.aborted && mounted.current) {
        setBinding({ kb, currentProvider: '', selectedProvider: '', canEdit: false, loading: false, error: `当前绑定读取失败：${errorMessage(error)}` })
      }
    }
  }

  function closeBinding() {
    if (bindingSavingRef.current) return
    if (bindingDirty && !window.confirm('有未提交的引擎绑定更改，确定放弃？')) return
    bindingRequest.current?.abort()
    setBinding(null)
  }

  async function saveBinding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!binding || !binding.canEdit || binding.loading || bindingSavingRef.current || submittingRef.current) return
    const latest = knowledgeBases.find((kb) => (kb.id ?? kb.name) === (binding.kb.id ?? binding.kb.name))
    const nextProvider = providers.find((provider) => provider.id === binding.selectedProvider)
    if (!latest || bindingRestriction(latest) || !CREATE_ENGINES.has(binding.currentProvider) || !nextProvider || !CREATE_ENGINES.has(nextProvider.id) || resourceErrors.providers) return
    if (binding.currentProvider === nextProvider.id) return
    const currentLabel = providers.find((provider) => provider.id === binding.currentProvider)?.name ?? binding.currentProvider
    if (!window.confirm(`确认将知识库「${binding.kb.name}」的引擎由 ${currentLabel} 改为 ${nextProvider.name}？已有就绪索引可能被后端拒绝（409）；成功后仍需手动重建。本操作不会自动迁移或重建索引。`)) return
    bindingSavingRef.current = true
    setBindingSaving(true)
    setBindingNotice('')
    setBinding((previous) => previous && ({ ...previous, error: '' }))
    try {
      await settingsRequest<KnowledgeConfig>(knowledgeConfigPath(binding.kb), {
        method: 'PUT', body: JSON.stringify({ rag_provider: nextProvider.id }),
      })
      if (!mounted.current) return
      setBindingNotice(`知识库「${binding.kb.name}」的引擎配置已更新，需要后续手动重建；索引尚未确认就绪，未启动迁移或重建任务。`)
      setBinding(null)
      setHasUnsavedChanges(false)
      await refreshLists()
    } catch (error) {
      if (mounted.current) setBinding((previous) => previous && ({ ...previous, error: errorMessage(error) }))
    } finally {
      bindingSavingRef.current = false
      if (mounted.current) setBindingSaving(false)
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submittingRef.current || bindingSavingRef.current) return
    setSubmitError('')
    if (!name.trim()) {
      setSubmitError('请输入知识库名称')
      return
    }
    if (!canCreate || loading || resourceErrors.providers) {
      setSubmitError('请先读取引擎目录，并选择支持通用建库的引擎')
      return
    }
    if (usesEmbedding && embedding && !models?.options.some((option) => embeddingValue(option) === embedding)) {
      setSubmitError('所选嵌入模型当前不可用，请重新选择，或明确选择现有默认配置')
      return
    }
    const body = new FormData()
    body.append('name', name.trim())
    body.append('rag_provider', engine)
    if (usesEmbedding && embedding) body.append('embedding_model', embedding)
    for (const file of files) body.append('files', file)
    submittingRef.current = true
    setSubmitting(true)
    setSubmitted(null)
    setRefreshError('')
    try {
      const result = await settingsRequest<CreationTask>('/api/knowledge-bases', { method: 'POST', body })
      if (!mounted.current) return
      setSubmitted(result)
      resetForm()
      setFormOpen(false)
      await refreshLists(true)
    } catch (error) {
      if (mounted.current) setSubmitError(errorMessage(error))
    } finally {
      submittingRef.current = false
      if (mounted.current) setSubmitting(false)
    }
  }

  return <section className="settings-card mb-5 space-y-4" aria-labelledby={`${formId}-heading`}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 id={`${formId}-heading`} className="flex items-center gap-2 text-lg font-semibold text-ink">
          <Database size={20} aria-hidden="true" />知识库连接
        </h2>
        <p className="mt-1 text-sm text-ink-2">管理真实知识库连接、建库任务与知识库引擎绑定。</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="settings-button-secondary" disabled={loading || busy} onClick={() => { void refreshLists() }}>
          <RefreshCw size={16} aria-hidden="true" />{loading ? '读取中…' : '刷新列表'}
        </button>
        <button type="button" className="settings-button-secondary" disabled={busy} onClick={() => openEngineSettings()}>
          <Settings2 size={16} aria-hidden="true" />配置引擎
        </button>
        {!formOpen && <button type="button" className="settings-button" disabled={busy} onClick={openCreation}>
          <Plus size={16} aria-hidden="true" />新建知识库
        </button>}
      </div>
    </div>

    {resourceErrors.knowledge && <p className="settings-error" role="alert">知识库列表读取失败：{resourceErrors.knowledge}。可刷新重试，已有列表可能过期。</p>}
    {resourceErrors.providers && <p className="settings-error" role="alert">引擎目录读取失败：{resourceErrors.providers}。可刷新重试。</p>}
    {refreshError && <p className="settings-error" role="alert">{refreshError}</p>}
    {bindingNotice && <p className="settings-note" role="status">{bindingNotice}</p>}
    {submitted && <div className="settings-note" role="status">
      <p>知识库「{submitted.name}」已提交后台任务，索引尚未确认就绪。请刷新列表查看后端状态。</p>
      <p className="break-all">任务编号：{submitted.task_id}</p>
    </div>}

    <div aria-busy={loading}>
      {loading && <p className="mb-2 text-sm text-ink-2" role="status">正在读取真实知识库与引擎目录…</p>}
      {!loading && !resourceErrors.knowledge && knowledgeBases.length === 0 && <p className="rounded-lg border border-dashed border-line p-4 text-sm text-ink-2">尚无真实知识库，可新建本地知识库或查看引擎配置。</p>}
      {knowledgeBases.length > 0 && <ul className="divide-y divide-line rounded-lg border border-line">
        {knowledgeBases.map((kb) => {
          const providerId = kb.metadata?.rag_provider
          const provider = providers.find((item) => item.id === providerId)
          const restriction = bindingRestriction(kb)
          const status = kb.available === false ? 'unavailable' : kb.status
          return <li key={kb.id ?? kb.name} className="flex flex-wrap items-center justify-between gap-3 p-3">
            <div className="min-w-0 flex-1 basis-48">
              <p className="break-words font-medium text-ink">{kb.name}</p>
              <p className="mt-1 break-words text-sm text-ink-2">
                引擎：{provider?.name ?? providerId ?? '后端未返回'} · 状态：{status ? STATUS_LABELS[status] ?? status : '后端未返回'}
                {kb.metadata?.needs_reindex && ' · 需要重建索引'}
              </p>
              {restriction && <p className="mt-1 text-sm text-ink-2">{restriction}</p>}
              {kb.metadata?.last_error && <p className="mt-1 break-words text-sm text-danger">{kb.metadata.last_error}</p>}
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="settings-button-secondary" disabled={!providerId || busy} onClick={() => openEngineSettings(providerId)} aria-label={`配置${kb.name}的${provider?.name ?? providerId ?? ''}引擎`}>
                配置引擎
              </button>
              <button type="button" className="settings-button-secondary" disabled={!!restriction || busy || loading || !!resourceErrors.providers} title={restriction || '读取当前绑定后选择新引擎'} onClick={() => { void openBinding(kb) }} aria-label={`更改${kb.name}的引擎绑定`}>
                更改引擎
              </button>
            </div>
          </li>
        })}
      </ul>}
    </div>

    {providers.length > 0 && <details className="rounded-lg border border-line p-3">
      <summary className="cursor-pointer text-sm font-medium text-ink">查看引擎目录与现有能力</summary>
      <ul className="mt-3 space-y-3">
        {providers.map((provider) => <li key={provider.id} className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0 flex-1 basis-48">
            <p className="text-sm font-medium text-ink">{provider.name} · 配置标记：{provider.configured ? '是' : '否'}</p>
            <p className="mt-1 text-sm text-ink-2">{CREATE_ENGINES.has(provider.id) ? '支持本次建库选择。' : CONNECT_NOTES[provider.id] ?? '此引擎未核实通用建库能力，此入口仅提供配置。'}{provider.readiness_reason && ` ${provider.readiness_reason}`}</p>
          </div>
          <button type="button" className="settings-button-secondary" disabled={submitting} onClick={() => openEngineSettings(provider.id)} aria-label={`配置 ${provider.name}`}>配置</button>
        </li>)}
      </ul>
      <p className="mt-3 text-sm text-ink-2">配置标记不代表依赖、连接或索引已就绪；远端专用连接需沿用已有工作流。</p>
    </details>}

    {binding && <form className="space-y-4 rounded-lg border border-line p-4" onSubmit={(event) => { void saveBinding(event) }} aria-labelledby={`${formId}-binding`}>
      <h3 id={`${formId}-binding`} className="font-semibold text-ink">更改「{binding.kb.name}」的引擎绑定</h3>
      {binding.loading && <p role="status" className="text-sm text-ink-2">正在读取此库当前配置…</p>}
      {!binding.loading && CREATE_ENGINES.has(binding.currentProvider) && <label className="settings-label" htmlFor={`${formId}-binding-engine`}>目标绑定引擎
        <span className="text-sm font-normal text-ink-2">当前配置：{providers.find((provider) => provider.id === binding.currentProvider)?.name ?? binding.currentProvider}</span>
        <select id={`${formId}-binding-engine`} className="settings-input" value={binding.selectedProvider} disabled={bindingSaving || loading || !!resourceErrors.providers || !!bindingRestriction(binding.kb) || !binding.canEdit} onChange={(event) => setBinding((previous) => previous && ({ ...previous, selectedProvider: event.target.value, error: '' }))}>
          {!providers.some((provider) => provider.id === binding.selectedProvider && CREATE_ENGINES.has(provider.id)) && <option value={binding.selectedProvider}>{binding.selectedProvider}</option>}
          {providers.filter((provider) => CREATE_ENGINES.has(provider.id)).map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
        </select>
      </label>}
      <p className="settings-note">已有就绪索引可能返回后端 409 冲突；确认只提交该库的引擎绑定。成功后需要后续手动重建，不会自动迁移、删除索引或启动重建。</p>
      {binding.error && <p className="settings-error" role="alert">{binding.error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className="settings-button" disabled={!binding.canEdit || !bindingDirty || binding.loading || bindingSaving || loading || !CREATE_ENGINES.has(binding.currentProvider) || !providers.some((provider) => provider.id === binding.selectedProvider && CREATE_ENGINES.has(provider.id)) || !!resourceErrors.providers}>{bindingSaving ? '正在提交绑定…' : '确认变更绑定'}</button>
        <button type="button" className="settings-button-secondary" disabled={bindingSaving} onClick={closeBinding}>取消绑定编辑</button>
      </div>
    </form>}
    {formOpen && <form className="space-y-4 border-t border-line pt-4" onSubmit={(event) => { void submit(event) }} aria-labelledby={`${formId}-create`}>
      <h3 id={`${formId}-create`} className="font-semibold text-ink">新建真实知识库</h3>
      <fieldset disabled={submitting} className="grid min-w-0 gap-4 sm:grid-cols-2">
        <label className="settings-label" htmlFor={`${formId}-name`}>知识库名称
          <input id={`${formId}-name`} className="settings-input" required value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="settings-label" htmlFor={`${formId}-engine`}>本次建库引擎
          <select id={`${formId}-engine`} className="settings-input" value={engine} disabled={loading || !!resourceErrors.providers} onChange={(event) => { setEngine(event.target.value); setEmbedding('') }}>
            {!selectedProvider && <option value={engine}>请先读取引擎目录</option>}
            {providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}{CREATE_ENGINES.has(provider.id) ? '' : '（需专用连接）'}</option>)}
          </select>
        </label>
        {canCreate && usesEmbedding && <label className="settings-label sm:col-span-2" htmlFor={`${formId}-embedding`}>本次建库嵌入模型
          <select id={`${formId}-embedding`} className="settings-input" value={embedding} aria-describedby={`${formId}-embedding-note`} onChange={(event) => setEmbedding(event.target.value)}>
            <option value="">使用后端现有默认{activeModel ? `：${activeModel.profile_name} / ${activeModel.label}` : '（由后端校验）'}</option>
            {embedding && !models?.options.some((option) => embeddingValue(option) === embedding) && <option value={embedding} disabled>此前选择当前不可用，请重新选择</option>}
            {models?.options.map((option) => <option key={embeddingValue(option)} value={embeddingValue(option)}>{option.profile_name} / {option.label}{option.detail ? ` · ${option.detail}` : ''}</option>)}
          </select>
          <span id={`${formId}-embedding-note`} className="text-sm font-normal text-ink-2">仅绑定此次新建知识库；使用默认时由后端解析当前正式配置。</span>
        </label>}
        {canCreate && <label className="settings-label sm:col-span-2" htmlFor={`${formId}-files`}>初始文件（可选，可多选）
          <input ref={fileInput} id={`${formId}-files`} className="settings-input" type="file" multiple onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
          <span className="break-words text-sm font-normal text-ink-2">{files.length > 0 ? `已选择 ${files.length} 个文件：${files.map((file) => file.name).join('、')}` : '不选文件也可提交。文件格式与上传限制以所选引擎的后端校验为准。'}</span>
        </label>}
      </fieldset>
      {selectedProvider && !canCreate && <p className="settings-note">{CONNECT_NOTES[engine] ?? '此引擎尚未核实通用建库能力，请沿用现有专用连接流程。'} 此表单不会为该引擎发送建库请求。</p>}
      {canCreate && usesEmbedding && resourceErrors.embedding && <p className="settings-error" role="alert">嵌入模型选项读取失败：{resourceErrors.embedding}。可刷新重试，或选择使用后端现有默认。</p>}
      <p className="settings-note">引擎与嵌入选择仅用于此次新建知识库，不切换全局默认，不修改已有知识库绑定，也不会自动迁移或重建旧索引。</p>
      {submitError && <p className="settings-error" role="alert">建库请求失败：{submitError}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className="settings-button" disabled={submitting || loading || !canCreate || !!resourceErrors.providers}>{submitting ? '正在提交…' : '提交建库任务'}</button>
        <button type="button" className="settings-button-secondary" disabled={submitting} onClick={closeForm}>取消</button>
        <button type="button" className="settings-button-secondary" disabled={submitting || !selectedProvider} onClick={() => openEngineSettings(engine)}>配置所选引擎</button>
      </div>
    </form>}
  </section>
}
