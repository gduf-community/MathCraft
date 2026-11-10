import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { getAdminRagSettings, rebuildAdminRagSettings, saveAdminRagSettings, testAdminRagSettings } from '../../api/adminRagSettings'
import type { AdminRagSettings, RagService } from '../../api/adminRagSettings'
import { ApiError } from '../../api/session'
import { useToast } from '../../store/ToastContext'

interface ServiceDraft { model: string; baseUrl: string; apiKey: string }
interface SettingsDraft { embedding: ServiceDraft; rerank: ServiceDraft }
type FieldErrors = Partial<Record<RagService, string>>

const EMPTY_DRAFT: SettingsDraft = {
  embedding: { model: '', baseUrl: '', apiKey: '' },
  rerank: { model: '', baseUrl: '', apiKey: '' },
}
const STATUS_LABELS = {
  idle: '尚未启动', queued: '等待重建', running: '正在重建', succeeded: '重建成功', failed: '重建失败',
}
const INPUT_CLASS = 'mt-1 min-h-11 w-full min-w-0 rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-page'
const BUTTON_CLASS = 'min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-ink-2 hover:bg-page focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-60'

function toDraft(snapshot: AdminRagSettings): SettingsDraft {
  const embedding = snapshot.pending ?? snapshot.active
  return {
    embedding: { model: embedding.embedding_model, baseUrl: embedding.embedding_base_url, apiKey: '' },
    rerank: { model: snapshot.active.rerank_model, baseUrl: snapshot.active.rerank_base_url, apiKey: '' },
  }
}

function validateService(draft: ServiceDraft): string | undefined {
  if (!draft.model.trim()) return '请填写模型名称'
  try {
    const url = new URL(draft.baseUrl.trim())
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password
      || url.href.includes('?') || url.href.includes('#')) {
      return '请使用 http(s) 服务地址，不可包含用户名、密码、查询参数或片段'
    }
  } catch {
    return '请填写完整的 http(s) 服务地址'
  }
  return undefined
}

function isRebuilding(snapshot: AdminRagSettings | null): boolean {
  return snapshot?.rebuild.status === 'queued' || snapshot?.rebuild.status === 'running'
}

function ragErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return '当前后端未提供模型与检索接口，请确认已完成数据库迁移并重启到当前版本'
    if (error.status === 502 || error.status === 503 || error.status === 504) return '后端或数据服务暂不可用，请检查服务运行状态后重试'
    if (error.code === 'RAG_SETTINGS_CONFLICT') return '配置已被更新，请刷新状态并载入已保存配置后重试'
    if (error.code === 'RAG_REBUILD_BUSY') return '索引正在重建，请刷新状态查看进度，完成后再修改配置'
    if (error.code === 'RAG_INGESTION_BUSY') return '资料正在处理，请等待处理完成后重试重建'
  }
  if (error instanceof TypeError) return '无法连接后端，请检查网络和后端服务是否已启动'
  return error instanceof Error ? error.message : '操作失败，请重试'
}

interface RagSettingsPanelProps {
  onDirtyChange?: (dirty: boolean) => void
  onBusyChange?: (busy: boolean) => void
}

/** 管理员系统配置；草稿只保存在组件内存，刷新状态不会覆盖编辑内容。 */
export function RagSettingsPanel({ onDirtyChange, onBusyChange }: RagSettingsPanelProps) {
  const { showToast } = useToast()
  const [snapshot, setSnapshot] = useState<AdminRagSettings | null>(null)
  const [draft, setDraft] = useState<SettingsDraft>(EMPTY_DRAFT)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [loadError, setLoadError] = useState('')
  const [refreshing, setRefreshing] = useState(true)
  const [refreshVersion, setRefreshVersion] = useState(0)
  const [busy, setBusyState] = useState<'save' | 'rebuild' | RagService | null>(null)
  const [confirmRebuild, setConfirmRebuild] = useState(false)
  const [draftRevision, setDraftRevision] = useState<number | null>(null)
  const snapshotRef = useRef<AdminRagSettings | null>(null)
  const requestGeneration = useRef(0)
  const mutationBusy = useRef(false)
  const mounted = useRef(false)
  const running = isRebuilding(snapshot)

  function setBusy(value: 'save' | 'rebuild' | RagService | null) {
    setBusyState(value)
    onBusyChange?.(value !== null)
  }

  useEffect(() => () => onBusyChange?.(false), [onBusyChange])

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; requestGeneration.current += 1 }
  }, [])

  useEffect(() => {
    let active = true
    let inFlight = false
    async function load() {
      if (inFlight || mutationBusy.current) return
      inFlight = true
      const generation = ++requestGeneration.current
      setRefreshing(true)
      try {
        const next = await getAdminRagSettings()
        if (!active || generation !== requestGeneration.current) return
        const previous = snapshotRef.current
        if (previous && next.revision < previous.revision) return
        if (previous && next.revision !== previous.revision) setConfirmRebuild(false)
        snapshotRef.current = next
        setSnapshot(next)
        setLoadError('')
        if (!previous) { setDraft(toDraft(next)); setDraftRevision(next.revision) }
        if (isRebuilding(previous) && !isRebuilding(next)) {
          if (next.rebuild.status === 'succeeded') showToast('索引重建成功，已切换到新的嵌入配置', 'success')
          if (next.rebuild.status === 'failed') showToast('索引重建失败，旧配置继续可用，请查看错误后重试', 'error')
        }
      } catch (error: unknown) {
        if (active && generation === requestGeneration.current) {
          setLoadError(ragErrorMessage(error))
        }
      } finally {
        inFlight = false
        if (active && generation === requestGeneration.current) setRefreshing(false)
      }
    }
    void load()
    const timer = running ? window.setInterval(() => void load(), 2000) : undefined
    return () => { active = false; window.clearInterval(timer) }
  }, [refreshVersion, running, showToast])

  function edit(service: RagService, next: ServiceDraft) {
    setDraft(current => ({ ...current, [service]: next }))
    setErrors(current => ({ ...current, [service]: undefined }))
    setConfirmRebuild(false)
  }

  function acceptSnapshot(next: AdminRagSettings, resetDraft: boolean) {
    requestGeneration.current += 1
    snapshotRef.current = next
    setSnapshot(next)
    setLoadError('')
    setRefreshing(false)
    if (resetDraft) { setDraft(toDraft(next)); setDraftRevision(next.revision); setErrors({}) }
  }

  function reportError(error: unknown) {
    if (!mounted.current) return
    showToast(ragErrorMessage(error), 'error')
    if (error instanceof ApiError && ['RAG_SETTINGS_CONFLICT', 'RAG_REBUILD_BUSY', 'RAG_INGESTION_BUSY'].includes(error.code)) {
      setRefreshVersion(value => value + 1)
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const nextErrors = { embedding: validateService(draft.embedding), rerank: validateService(draft.rerank) }
    setErrors(nextErrors)
    if (nextErrors.embedding || nextErrors.rerank || !snapshot || mutationBusy.current || running) return
    if (draftRevision !== snapshot.revision) {
      showToast('配置版本已变化，请先载入已保存配置，再重新编辑', 'error')
      return
    }
    mutationBusy.current = true
    requestGeneration.current += 1
    setBusy('save')
    try {
      const next = await saveAdminRagSettings({
        embedding_model: draft.embedding.model.trim(), embedding_base_url: draft.embedding.baseUrl.trim(),
        ...(draft.embedding.apiKey.trim() ? { embedding_api_key: draft.embedding.apiKey.trim() } : {}),
        rerank_model: draft.rerank.model.trim(), rerank_base_url: draft.rerank.baseUrl.trim(),
        ...(draft.rerank.apiKey.trim() ? { rerank_api_key: draft.rerank.apiKey.trim() } : {}),
        revision: snapshot.revision,
      })
      if (!mounted.current) return
      acceptSnapshot(next, true)
      setConfirmRebuild(false)
      showToast(next.pending
        ? '配置已保存；嵌入配置需手动重建索引后应用，重排配置和仅密钥更新对后续请求生效'
        : '配置已保存，将用于后续请求', 'success')
    } catch (error: unknown) {
      reportError(error)
    } finally {
      mutationBusy.current = false
      if (mounted.current) { setBusy(null); setRefreshing(false) }
    }
  }

  async function test(service: RagService) {
    const values = draft[service]
    const error = validateService(values)
    setErrors(current => ({ ...current, [service]: error }))
    if (error || mutationBusy.current) return
    mutationBusy.current = true
    setBusy(service)
    try {
      const result = await testAdminRagSettings({
        service, model: values.model.trim(), base_url: values.baseUrl.trim(),
        ...(values.apiKey.trim() ? { api_key: values.apiKey.trim() } : {}),
      })
      if (mounted.current) showToast(result.message || '连接测试成功', 'success')
    } catch (error: unknown) {
      reportError(error)
    } finally {
      mutationBusy.current = false
      if (mounted.current) setBusy(null)
    }
  }

  async function rebuild() {
    if (!snapshot || mutationBusy.current || running || !confirmRebuild) return
    mutationBusy.current = true
    requestGeneration.current += 1
    setBusy('rebuild')
    try {
      const next = await rebuildAdminRagSettings(snapshot.revision)
      if (!mounted.current) return
      acceptSnapshot(next, false)
      setConfirmRebuild(false)
      showToast(next.rebuild.status === 'failed' ? '索引重建失败，旧配置继续可用'
        : next.rebuild.status === 'succeeded' ? '索引重建成功，已应用嵌入配置' : '重建已提交，可在此查看进度',
      next.rebuild.status === 'failed' ? 'error' : 'success')
    } catch (error: unknown) {
      reportError(error)
    } finally {
      mutationBusy.current = false
      if (mounted.current) { setBusy(null); setRefreshing(false) }
    }
  }

  const savedDraft = snapshot ? toDraft(snapshot) : EMPTY_DRAFT
  const dirty = (['embedding', 'rerank'] as const).some(service =>
    draft[service].model !== savedDraft[service].model || draft[service].baseUrl !== savedDraft[service].baseUrl
    || Boolean(draft[service].apiKey))
  const progress = Math.min(100, Math.max(0, snapshot?.rebuild.progress ?? 0))

  useEffect(() => { onDirtyChange?.(dirty) }, [dirty, onDirtyChange])
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange])
  useEffect(() => {
    if (!dirty && busy === null) return
    const preventLoss = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', preventLoss)
    return () => window.removeEventListener('beforeunload', preventLoss)
  }, [dirty, busy])

  return (
    <div className="min-w-0 space-y-5">
      <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="text-lg font-semibold">模型与检索</h2><p className="mt-2 text-sm text-ink-2">管理全平台嵌入与重排服务。保存嵌入模型或地址变更后，需另行确认重建才能应用。</p></div>
          <button type="button" className={BUTTON_CLASS} onClick={() => setRefreshVersion(value => value + 1)} aria-busy={refreshing}>{refreshing ? '刷新中…' : '刷新状态'}</button>
        </div>
        {loadError && <p role="alert" className="mt-4 break-words text-sm text-danger">状态刷新失败：{loadError}。处理后可刷新状态，现有编辑内容会保留。</p>}
        {!snapshot && <p role="status" className="mt-5 text-sm text-ink-2">{loadError ? '尚未载入配置，暂不可编辑。' : '正在读取系统配置…'}</p>}
      </section>

      {snapshot && <>
        <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
          <h3 className="font-semibold">当前生效配置</h3>
          <div className="mt-4 grid min-w-0 gap-5 md:grid-cols-2">
            <ConfigSummary title="嵌入服务" model={snapshot.active.embedding_model} url={snapshot.active.embedding_base_url} configured={snapshot.active.embedding_key_configured} />
            <ConfigSummary title="重排服务" model={snapshot.active.rerank_model} url={snapshot.active.rerank_base_url} configured={snapshot.active.rerank_key_configured} />
          </div>
          {snapshot.pending && <div className="mt-5 rounded-xl border border-primary/20 bg-primary-weak p-4">
            <p className="font-medium text-primary">已保存，待重建应用</p>
            <div className="mt-3"><ConfigSummary title="待应用嵌入服务" model={snapshot.pending.embedding_model} url={snapshot.pending.embedding_base_url} configured={snapshot.pending.embedding_key_configured} /></div>
            <p className="mt-3 text-sm text-ink-2">当前查询与出题继续使用上方生效配置。保存不会自动重建或切换。</p>
            <p className="mt-2 text-sm text-ink-2">如需取消待应用变更，将嵌入模型和地址改回当前生效值后保存。</p>
          </div>}
        </section>

        <form onSubmit={event => void save(event)} className="rounded-2xl border border-line bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-semibold">编辑配置{dirty ? ' · 有未保存修改' : ''}</h3>
            <button type="button" disabled={Boolean(busy) || running} className={BUTTON_CLASS} onClick={() => {
              setDraft(toDraft(snapshot)); setDraftRevision(snapshot.revision); setErrors({}); setConfirmRebuild(false)
            }}>载入已保存配置</button>
          </div>
          {draftRevision !== snapshot.revision && <p role="status" className="mt-3 text-sm text-primary">配置版本已变化，草稿保留。请先载入已保存配置，再重新编辑。</p>}
          <fieldset disabled={Boolean(busy) || running} className="mt-5 min-w-0">
            <legend className="sr-only">嵌入与重排服务配置</legend>
            <div className="grid min-w-0 gap-6 xl:grid-cols-2">
              {(['embedding', 'rerank'] as const).map(service => <ServiceFields key={service} service={service} value={draft[service]}
                error={errors[service]} testing={busy === service} onChange={value => edit(service, value)} onTest={() => void test(service)} />)}
            </div>
          </fieldset>
          <p className="mt-5 text-sm text-ink-2">密钥留空保留已有值，不提供清除功能。输入的密钥仅在内存中保留；连接测试只使用本次草稿，不保存配置。</p>
          <p className="mt-2 text-sm text-ink-2">仅更新密钥及重排配置用于后续请求；嵌入模型或地址变更需重建后切换。</p>
          <button type="submit" disabled={Boolean(busy) || running || !dirty || draftRevision !== snapshot.revision} className="mt-5 min-h-11 rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-60">{busy === 'save' ? '保存中…' : '保存配置'}</button>
        </form>

        <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
          <h3 className="font-semibold">索引重建与应用</h3>
          <p className="mt-2 text-sm text-ink-2">复用已解析片段，无需重新 OCR。重建期间暂停资料变更，旧库继续支持查询和出题；成功后切换，失败时旧配置继续可用。</p>
          <div className="mt-4 rounded-xl bg-page p-4" role="status" aria-live="polite">
            <p className="text-sm font-medium">{STATUS_LABELS[snapshot.rebuild.status]}{running ? ' · 每 2 秒更新状态' : ''}</p>
            <p className="mt-2 break-words text-sm text-ink-2">{snapshot.rebuild.stage || '暂无重建任务'}</p>
            <div className="mt-3 flex items-center gap-3"><progress aria-label="索引重建进度" max={100} value={progress} className="h-2 w-full min-w-0 accent-primary" /><span className="shrink-0 text-sm">{Math.round(progress)}%</span></div>
          </div>
          {snapshot.rebuild.error && <p role="alert" className="mt-3 break-words text-sm text-danger">{snapshot.rebuild.error}</p>}
          {dirty && <p className="mt-3 text-sm text-ink-2">请先保存或载入已保存配置；重建仅应用服务器已保存的配置。</p>}
          {confirmRebuild ? <div className="mt-4 rounded-xl border border-primary/20 bg-primary-weak p-4">
            <p className="text-sm font-medium">确认使用已保存配置重建索引？</p>
            <p className="mt-2 text-sm text-ink-2">重建期间所有用户暂时无法变更资料。任务提交后可离开页面，回来刷新查看进度。</p>
            <div className="mt-4 flex flex-wrap gap-3"><button type="button" disabled={Boolean(busy) || running || dirty} onClick={() => void rebuild()} className="min-h-11 rounded-lg bg-primary px-4 py-2 text-sm text-white disabled:opacity-60">{busy === 'rebuild' ? '提交中…' : '确认重建并应用'}</button><button type="button" disabled={Boolean(busy)} onClick={() => setConfirmRebuild(false)} className={BUTTON_CLASS}>取消</button></div>
          </div> : <button type="button" disabled={Boolean(busy) || running || dirty || (!snapshot.pending && snapshot.rebuild.status !== 'failed')} onClick={() => setConfirmRebuild(true)} className={`mt-4 ${BUTTON_CLASS}`}>{snapshot.rebuild.status === 'failed' ? '重试重建' : '重建索引并应用'}</button>}
        </section>

        <section className="min-w-0 rounded-2xl border border-line bg-white p-5 shadow-sm">
          <h3 className="font-semibold">向量存储</h3>
          <dl className="mt-4 space-y-3 text-sm"><div><dt className="text-ink-2">类型</dt><dd className="mt-1">Chroma · 只读</dd></div><div><dt className="text-ink-2">存储路径</dt><dd className="mt-1 break-all font-mono">{snapshot.vector_store.path || '未提供'}</dd></div><div><dt className="text-ink-2">可用状态</dt><dd className="mt-1">{snapshot.vector_store.available ? '可用' : '不可用'}</dd></div></dl>
          {snapshot.vector_store.message && <p className="mt-3 break-words text-sm text-ink-2">{snapshot.vector_store.message}</p>}
        </section>
      </>}
    </div>
  )
}

interface ServiceFieldsProps {
  service: RagService
  value: ServiceDraft
  error?: string
  testing: boolean
  onChange: (value: ServiceDraft) => void
  onTest: () => void
}

function ServiceFields({ service, value, error, testing, onChange, onTest }: ServiceFieldsProps) {
  const title = service === 'embedding' ? '嵌入服务' : '重排服务'
  return <section className="min-w-0 space-y-4">
    <h4 className="font-medium">{title}</h4>
    <label className="block text-sm text-ink-2" htmlFor={`${service}-model`}>模型名称<input id={`${service}-model`} className={INPUT_CLASS} value={value.model} onChange={event => onChange({ ...value, model: event.target.value })} required /></label>
    <label className="block text-sm text-ink-2" htmlFor={`${service}-url`}>服务地址<input id={`${service}-url`} type="url" className={INPUT_CLASS} placeholder="https://api.example.com/v1" value={value.baseUrl} onChange={event => onChange({ ...value, baseUrl: event.target.value })} aria-invalid={Boolean(error)} aria-describedby={error ? `${service}-error` : undefined} required /></label>
    <label className="block text-sm text-ink-2" htmlFor={`${service}-key`}>API 密钥<input id={`${service}-key`} type="password" autoComplete="new-password" spellCheck={false} className={INPUT_CLASS} placeholder="留空保留已保存密钥" value={value.apiKey} onChange={event => onChange({ ...value, apiKey: event.target.value })} /></label>
    {error && <p id={`${service}-error`} role="alert" className="text-sm text-danger">{error}</p>}
    <button type="button" onClick={onTest} className={BUTTON_CLASS}>{testing ? '测试中…' : `测试${title}`}</button>
  </section>
}

function ConfigSummary({ title, model, url, configured }: { title: string; model: string; url: string; configured: boolean }) {
  return <div className="min-w-0"><p className="text-sm font-medium">{title}</p><p className="mt-2 break-all text-sm">{model || '未配置模型'}</p><p className="mt-1 break-all text-sm text-ink-2">{url || '未配置服务地址'}</p><p className="mt-2 text-sm text-ink-2">密钥：{configured ? '已配置 · 内容隐藏' : '未配置'}</p></div>
}
