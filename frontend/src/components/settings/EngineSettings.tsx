import { useEffect, useRef, useState } from 'react'
import { getEngineConfig, getEngineProviders, preflightEngine, probeKiwix, probeWeKnora, saveEngineConfig, saveEngineMode } from '../../api/engineSettings'
import type { CheckResult, ConfigEngine, ConfigValues, EngineSettingsProps, RagProvider } from '../../types/engineSettings'
import { EngineParsingFields, mayLeaveSettings, numberField, secretField, selectField, settingsError, settingsPayload, SettingsCheckResult, toggleField, urlField, useSettingsDirty, validateSettings } from './EngineParsingFields'
import type { SettingsField } from './EngineParsingFields'
import { LightRagRoleFields, serializeLightRagRoles, validateLightRagRoles } from './LightRagRoleFields'

const engineFields: Record<ConfigEngine, SettingsField[]> = {
  llamaindex: [selectField('retrieval_profile', '检索策略', ['hybrid', 'vector']), numberField('top_k', '返回片段数', 1, 50), numberField('vector_top_k_multiplier', '向量候选倍数', 1, 10), numberField('bm25_top_k_multiplier', 'BM25 候选倍数', 1, 10), { key: 'reranker_model', label: '重排模型（留空禁用）' }, numberField('rerank_top_k', '重排候选数', 1, 100), selectField('vector_index_type', '向量索引类型', ['flat', 'hnsw']), numberField('hnsw_m', 'HNSW 邻居数', 4, 64), numberField('hnsw_ef_construction', 'HNSW 构建搜索宽度', 16, 512), numberField('hnsw_ef_search', 'HNSW 查询搜索宽度', 1, 512), numberField('chunk_size', '文档切分大小', 64, 8192), numberField('chunk_overlap', '片段重叠大小', 0, 8191), numberField('image_description_concurrency', '图像描述并发数', 1, 16), numberField('image_description_batch_size', '图像描述批大小', 1, 8), numberField('image_description_timeout_seconds', '图像描述超时（秒）', 5, 600)],
  pageindex: [secretField('api_key', 'PageIndex Cloud API Key')],
  ima: [{ key: 'client_id', label: 'IMA Client ID', required: true }, secretField('api_key', 'IMA API Key')],
  graphrag: [{ key: 'response_type', label: '回答风格', required: true }, numberField('community_level', '社区层级', 0, 5), toggleField('dynamic_community_selection', '全局检索动态选择社区')],
  lightrag: [numberField('top_k', '实体／关系召回数', 1, 200), { key: 'response_type', label: '回答风格', required: true }, numberField('max_concurrent_files', '索引文件并发数', 1, 16), numberField('llm_model_max_async', 'LLM 并发数', 1, 32), numberField('entity_extract_max_gleaning', '实体补充提取次数', 0, 5), numberField('llm_timeout', 'LLM 超时（秒）', 60, 3600)],
  'lightrag-server': [urlField('server_url', 'LightRAG Server 地址'), secretField('api_key', '服务 API Key')],
}
const isConfigEngine = (engine: string): engine is ConfigEngine => Object.prototype.hasOwnProperty.call(engineFields, engine)
const specialFields = (engine: string): SettingsField[] => [urlField('server_url', '服务地址'), ...(engine === 'weknora' ? [{ key: 'api_key', label: '本次检查使用的 API Key', kind: 'text' as const, required: true }, { key: 'knowledge_base_id', label: '远端知识库 ID', required: true }] : [{ key: 'zim_name', label: 'ZIM 名称（精确名称）', required: true }])]

function EngineDetail({ provider, onDirtyChange, onBusyChange, onModeSaved }: { provider: RagProvider; onDirtyChange: (dirty: boolean) => void; onBusyChange: (busy: boolean) => void; onModeSaved: (engine: string, mode: string) => void }) {
  const { id: engine } = provider
  const [values, setValues] = useState<ConfigValues>({})
  const [saved, setSaved] = useState<ConfigValues>({})
  const [mode, setMode] = useState(provider.default_mode ?? '')
  const [savedMode, setSavedMode] = useState(provider.default_mode ?? '')
  const [loading, setLoading] = useState(isConfigEngine(engine))
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [receipt, setReceipt] = useState('')
  const [result, setResult] = useState<CheckResult | null>(null)
  const [busy, setBusy] = useState('')
  const actionLock = useRef(false)
  const [attempt, setAttempt] = useState(0)
  const [revision, setRevision] = useState(0)
  const special = engine === 'weknora' || engine === 'kiwix'
  const fields = isConfigEngine(engine) ? [...engineFields[engine], ...(engine === 'lightrag' && values.version === 1 && !values.role_models ? [{ key: 'llm_profile_id', label: '专用模型 Profile ID（与模型 ID 配对）' }, { key: 'llm_model_id', label: '专用模型 ID' }] : [])] : special ? specialFields(engine) : []
  const dirty = JSON.stringify(values) !== JSON.stringify(saved) || mode !== savedMode
  useEffect(() => { onDirtyChange(dirty) }, [dirty, onDirtyChange])
  useEffect(() => {
    if (!isConfigEngine(engine)) return
    let active = true
    setLoading(true); setLoadError('')
    async function load() {
      try {
        const data = await getEngineConfig(engine as ConfigEngine)
        if (active) { setValues(data); setSaved(data); setRevision(value => value + 1) }
      } catch (error) { if (active) setLoadError(settingsError(error)) }
      finally { if (active) setLoading(false) }
    }
    void load()
    return () => { active = false }
  }, [engine, attempt])
  function edit(key: string, value: ConfigValues[string]) { setValues(current => ({ ...current, [key]: value })); setError(''); setErrors({}); setReceipt(''); setResult(null) }
  async function run(kind: 'save' | 'check' | 'mode') {
    if (actionLock.current) return
    setError(''); setReceipt('')
    if (kind === 'save' || (kind === 'check' && special)) {
      const invalid = validateSettings(fields, values)
      if (engine === 'llamaindex' && Number(values.chunk_overlap) >= Number(values.chunk_size)) invalid.chunk_overlap = '片段重叠必须小于切分大小'
      const rolesError = kind === 'save' && values.role_models ? validateLightRagRoles(values.role_models as ConfigValues) : ''
      if (Object.keys(invalid).length || rolesError) { setErrors(invalid); setError(rolesError || '请修正表单中的错误'); return }
      if (engine === 'lightrag' && Boolean(values.llm_profile_id) !== Boolean(values.llm_model_id) && !values.role_models) { setError('专用模型需要同时填写 Profile ID 与模型 ID'); return }
    }
    actionLock.current = true; setBusy(kind); onBusyChange(true)
    try {
      if (kind === 'save' && isConfigEngine(engine)) {
        const payload = settingsPayload(fields, values)
        if (values.role_models) { delete payload.llm_profile_id; delete payload.llm_model_id; payload.role_models = serializeLightRagRoles(values.role_models as ConfigValues) }
        const data = await saveEngineConfig(engine, payload)
        setValues(data); setSaved(data); setRevision(value => value + 1); setResult(null)
        setReceipt('配置已保存。检索参数作用于后续查询；索引参数作用于后续处理或重建。')
      } else if (kind === 'mode') {
        const data = await saveEngineMode(engine, mode)
        if (data.mode !== mode) throw new Error('后端返回的检索模式不一致，请重新读取')
        setSavedMode(mode); onModeSaved(engine, mode); setResult(null); setReceipt('此引擎的检索模式已保存。')
      } else if (special) {
        const data = engine === 'weknora'
          ? await probeWeKnora({ server_url: String(values.server_url ?? ''), api_key: String(values.api_key ?? ''), knowledge_base_id: String(values.knowledge_base_id ?? '') })
          : await probeKiwix({ server_url: String(values.server_url ?? ''), zim_name: String(values.zim_name ?? '') })
        setResult(data)
      } else if (isConfigEngine(engine) || engine === 'pageindex-oss') setResult(await preflightEngine(engine))
    } catch (error) { setError(settingsError(error)) }
    finally { actionLock.current = false; setBusy(''); onBusyChange(false) }
  }
  if (loading) return <p className="settings-note" role="status">正在读取引擎配置…</p>
  if (loadError) return <div role="alert" className="settings-error">{loadError}<button type="button" className="settings-button-secondary ml-2" onClick={() => setAttempt(value => value + 1)}>重试读取配置</button></div>
  return <section className="settings-card min-w-0 space-y-5" aria-label={`${provider.name}配置`}>
    <div><h3 className="text-lg font-semibold text-slate-900">{provider.name}</h3><p className="settings-note mt-2">{provider.description}</p></div>
    <p className="settings-note">{engine === 'kiwix' ? '此服务没有全局配置目录。' : `目录配置标记：${(values.configured ?? provider.configured) ? '已设置' : '未设置'}。`}{provider.setup_required ? '需要设置连接。' : ''}依赖、权限与连接可达性仍需检查；{result ? '本次检查覆盖的具体项目见下方。' : '尚未检查。'}</p>
    {provider.readiness_reason && <p className="settings-note">{provider.readiness_reason}</p>}
    {isConfigEngine(engine) && <p className="settings-note">{values.api_key_set !== undefined ? `凭据${values.api_key_set ? '已保存' : '未保存'}。` : ''}{values.effective_retrieval_profile ? `实际检索策略：${values.effective_retrieval_profile}。` : ''}本页不切换全局默认引擎，不迁移或重建现有索引。{engine === 'lightrag-server' ? '此服务仅保存可复用连接默认值，已有知识库绑定独立保留。' : ''}</p>}
    {special && <p className="settings-note">仅使用本次输入检查远端知识库，不保存全局配置，不注册知识库。连接／注册请在知识库页面完成。输入离开后不保留。</p>}
    {engine === 'pageindex-oss' && <p className="settings-note">本地 PageIndex OSS 使用正式主语言模型建立 PDF 索引；后端没有独立可写参数，请在模型与服务中配置模型。Cloud 凭据不用于此模式。</p>}
    {error && <p className="settings-error" role="alert">{error}</p>}
    {receipt && <p role="status" className="text-sm text-blue-700">{receipt}</p>}
    <form noValidate onSubmit={event => { event.preventDefault(); void run(special ? 'check' : 'save') }} className="space-y-5">
      <EngineParsingFields key={revision} fields={fields.filter(field => !(special && field.key === 'api_key'))} values={values} onChange={edit} errors={errors} disabled={Boolean(busy)} />
      {engine === 'weknora' && <label className="settings-label block">本次检查 API Key<input type="password" autoComplete="new-password" className="settings-input mt-2" value={String(values.api_key ?? '')} disabled={Boolean(busy)} aria-invalid={Boolean(errors.api_key)} onChange={event => edit('api_key', event.target.value)} />{errors.api_key && <span className="settings-error" role="alert">{errors.api_key}</span>}</label>}
      {engine === 'lightrag' && (values.role_models
        ? <LightRagRoleFields roles={values.role_models as ConfigValues} disabled={Boolean(busy)} onChange={roles => edit('role_models', roles)} />
        : <button type="button" disabled={Boolean(busy)} className="settings-button-secondary" onClick={() => {
          const inherited = { mode: 'inherit', selection: null, reasoning_effort: null, max_async: 4, timeout: 240 }
          edit('role_models', { base: { profile_id: values.llm_profile_id ?? '', model_id: values.llm_model_id ?? '' }, extract: { ...inherited }, keyword: { ...inherited }, query: { ...inherited }, vlm: { ...inherited, mode: 'disabled' } })
        }}>配置专用模型与角色</button>)}
      <div className="flex flex-wrap items-center gap-3">
        {isConfigEngine(engine) && <button type="submit" className="settings-button" disabled={Boolean(busy) || JSON.stringify(values) === JSON.stringify(saved)}>{busy === 'save' ? '正在保存…' : '保存此引擎配置'}</button>}
        <button type="button" className="settings-button-secondary" disabled={Boolean(busy)} onClick={() => void run('check')}>{busy === 'check' ? '正在检查…' : special ? '测试远端连接' : '检查已保存配置'}</button>
        {dirty && <span className="settings-note">有未保存修改</span>}
      </div>
    </form>
    {!special && <p className="settings-note">预检只检查已保存配置与当前环境，不会写入未保存表单；检查通过不保证每次真实调用成功。</p>}
    <SettingsCheckResult result={result} />
    {Boolean(provider.modes?.length) && <fieldset disabled={Boolean(busy)} className="space-y-3 border-t border-slate-100 pt-4"><legend className="settings-label">此引擎的检索模式（独立保存）</legend>
      <select className="settings-input" aria-label="引擎检索模式" value={mode} onChange={event => { setMode(event.target.value); setReceipt('') }}>{provider.modes?.map(item => <option key={item}>{item}</option>)}</select>
      <button type="button" className="settings-button-secondary" disabled={mode === savedMode} onClick={() => void run('mode')}>{busy === 'mode' ? '正在保存模式…' : '保存检索模式'}</button>
    </fieldset>}
  </section>
}
export function EngineSettings({ initialEngine, onDirtyChange }: EngineSettingsProps) {
  const [providers, setProviders] = useState<RagProvider[]>([])
  const [selected, setSelected] = useState(initialEngine ?? 'llamaindex')
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const previousInitial = useRef(initialEngine)
  useSettingsDirty(dirty, onDirtyChange)
  useEffect(() => {
    if (initialEngine !== previousInitial.current) {
      previousInitial.current = initialEngine
      if (initialEngine && !busy && mayLeaveSettings(dirty)) { setDirty(false); setSelected(initialEngine) }
    }
  }, [initialEngine, dirty, busy])
  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    async function load() {
      try { const data = await getEngineProviders(); if (active) setProviders(data.providers) }
      catch (error) { if (active) setError(settingsError(error)) }
      finally { if (active) setLoading(false) }
    }
    void load()
    return () => { active = false }
  }, [attempt])
  const catalog = [...providers, { id: 'kiwix', name: 'Kiwix', configured: false, description: '检查 kiwix-serve 中已加载的 ZIM 档案。此服务不在通用引擎目录中。' }]
  const provider = catalog.find(item => item.id === selected)
  return <div className="min-w-0 space-y-5">
    <div><h2 className="text-xl font-semibold text-slate-900">知识库引擎</h2><p className="settings-note mt-2">引擎按知识库选择；此页独立维护各引擎配置。全局默认仍为 LlamaIndex。</p></div>
    {loading && <p role="status">正在读取引擎目录…</p>}
    {error && <p role="alert" className="settings-error">{error}<button className="settings-button-secondary ml-2" onClick={() => setAttempt(value => value + 1)}>重试目录</button></p>}
    {!loading && !error && providers.length === 0 && <p className="settings-note">后端引擎目录为空，请重试或检查服务。</p>}
    {!loading && !error && <div className="grid min-w-0 gap-5 xl:grid-cols-[190px_minmax(0,1fr)]">
      <nav aria-label="知识库引擎列表" className="flex flex-wrap content-start gap-2 xl:flex-col">{catalog.map(item => <button type="button" key={item.id} disabled={busy} aria-pressed={selected === item.id} className={`rounded-xl border px-3 py-2 text-left text-sm focus-visible:outline-2 focus-visible:outline-blue-600 ${selected === item.id ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600'}`} onClick={() => { if (selected !== item.id && mayLeaveSettings(dirty)) { setDirty(false); setSelected(item.id) } }}>{item.name}</button>)}</nav>
      {provider ? <EngineDetail key={selected} provider={provider} onDirtyChange={setDirty} onBusyChange={setBusy} onModeSaved={(engine, mode) => setProviders(current => current.map(item => item.id === engine ? { ...item, default_mode: mode } : item))} /> : <p className="settings-note">此引擎不在后端目录中，请选择可用目录项。</p>}
    </div>}
  </div>
}
