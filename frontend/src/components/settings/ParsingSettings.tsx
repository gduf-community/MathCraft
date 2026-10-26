import { useEffect, useRef, useState } from 'react'
import { checkDocling, checkMineru, checkParser, checkTika, downloadMineruModels, downloadParserModels, getParsingSettings, installParser, saveParsingSettings } from '../../api/parsingSettings'
import type { CheckResult, ConfigValues } from '../../types/engineSettings'
import type { MineruDownloadRequest, ParserEngine, ParsingSettingsData, ParsingSettingsProps } from '../../types/parsingSettings'
import { EngineParsingFields, mayLeaveSettings, numberField, secretField, selectField, settingsError, settingsPayload, SettingsCheckResult, toggleField, urlField, useSettingsDirty, validateSettings } from './EngineParsingFields'
import type { SettingsField } from './EngineParsingFields'
import { ParsingTaskMonitor } from './ParsingTaskMonitor'

const parserNames: Record<ParserEngine, string> = { text_only: '内置文本提取', mineru: 'MinerU', docling: 'Docling', markitdown: 'MarkItDown', pymupdf4llm: 'PyMuPDF4LLM', liteparse: 'LiteParse', tika: 'Apache Tika' }
const fields: Record<ParserEngine, SettingsField[]> = {
  text_only: [],
  mineru: [selectField('mode', '运行模式', ['local', 'cloud']), urlField('api_base_url', 'MinerU Cloud 地址'), secretField('api_token', 'MinerU Cloud Token'), { key: 'local_cli_path', label: '本地 CLI 路径（留空自动探测）' }, selectField('model_download_source', '模型下载来源', ['huggingface', 'modelscope']), { key: 'model_download_endpoint', label: '下载镜像地址（留空使用官方地址）' }, selectField('model_version', '模型版本', ['pipeline', 'vlm']), { key: 'language', label: '识别语言', required: true }, toggleField('enable_formula', '识别公式'), toggleField('enable_table', '识别表格'), toggleField('is_ocr', '启用 OCR'), numberField('max_pages_per_part', '每批页数', 1, 200), toggleField('normalize_tiny_scans', '规范化小尺寸扫描页'), toggleField('allow_local_model_download', '允许解析时下载本地模型')],
  docling: [selectField('mode', '运行模式', ['local', 'remote']), urlField('api_base_url', 'Docling Serve 地址'), secretField('api_token', 'Docling Serve Token'), toggleField('do_ocr', '启用 OCR'), toggleField('do_table_structure', '解析表格结构'), toggleField('allow_local_model_download', '允许解析时下载本地模型')],
  markitdown: [toggleField('enable_llm_image_description', '使用视觉模型描述图片')],
  pymupdf4llm: [toggleField('write_images', '提取图片'), selectField('image_format', '图片格式', ['png', 'jpg', 'jpeg', 'webp']), numberField('image_dpi', '图片分辨率（DPI）', 72, 600)],
  liteparse: [selectField('image_mode', 'Markdown 图片展示', ['off', 'placeholder', 'embed']), toggleField('extract_links', '提取链接'), toggleField('extract_images', '提取图片文件'), numberField('max_pages', '最多页数（0 表示全部）', 0, 100000)],
  tika: [urlField('server_url', 'Tika Server 地址')],
}
const installable = new Set<ParserEngine>(['docling', 'markitdown', 'pymupdf4llm', 'liteparse'])

export function ParsingSettings({ onDirtyChange }: ParsingSettingsProps) {
  const [data, setData] = useState<ParsingSettingsData | null>(null)
  const [selected, setSelected] = useState<ParserEngine>('text_only')
  const [activeEngine, setActiveEngine] = useState<ParserEngine>('text_only')
  const [values, setValues] = useState<ConfigValues>({})
  const [caption, setCaption] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [receipt, setReceipt] = useState('')
  const [result, setResult] = useState<CheckResult | null>(null)
  const [busy, setBusy] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [revision, setRevision] = useState(0)
  const [jobRefresh, setJobRefresh] = useState(0)
  const [genericRunning, setGenericRunning] = useState<boolean | null>(null)
  const [mineruRunning, setMineruRunning] = useState<boolean | null>(null)
  const [capabilityError, setCapabilityError] = useState('')
  const previousJobs = useRef<{ generic: boolean | null; mineru: boolean | null }>({ generic: null, mineru: null })
  const [modelType, setModelType] = useState<MineruDownloadRequest['model_type']>('pipeline')
  const actionLock = useRef(false)
  const dirty = data !== null && (JSON.stringify(values) !== JSON.stringify(data.engines[selected] ?? {}) || caption !== data.image_caption || activeEngine !== data.engine)
  useSettingsDirty(dirty, onDirtyChange)
  useEffect(() => {
    let active = true
    setLoading(true); setLoadError('')
    async function load() {
      try {
        const response = await getParsingSettings()
        if (active) { setData(response); setSelected(response.engine); setActiveEngine(response.engine); setValues(response.engines[response.engine] ?? {}); setCaption(response.image_caption); setRevision(value => value + 1) }
      } catch (error) { if (active) setLoadError(settingsError(error)) }
      finally { if (active) setLoading(false) }
    }
    void load()
    return () => { active = false }
  }, [attempt])
  useEffect(() => {
    const previous = previousJobs.current
    previousJobs.current = { generic: genericRunning, mineru: mineruRunning }
    if (!(previous.generic === true && genericRunning === false) && !(previous.mineru === true && mineruRunning === false)) return
    let active = true
    async function refreshCapabilities() {
      try {
        const fresh = await getParsingSettings()
        if (active) {
          setCapabilityError('')
          setData(current => current ? { ...current, available_engines: fresh.available_engines, readiness: fresh.readiness, installable: fresh.installable, model_downloadable: fresh.model_downloadable, mineru: fresh.mineru, docling: fresh.docling } : current)
        }
      } catch (error) { if (active) setCapabilityError(`任务结束后刷新依赖状态失败：${settingsError(error)}。可用检查按钮重新验证，或重新进入页面。`) }
    }
    void refreshCapabilities()
    return () => { active = false }
  }, [genericRunning, mineruRunning])
  function edit(key: string, value: ConfigValues[string]) { setValues(current => ({ ...current, [key]: value })); setErrors({}); setError(''); setReceipt(''); setResult(null) }
  function changeParser(engine: ParserEngine) {
    if (!data || engine === selected || busy || !mayLeaveSettings(dirty)) return
    setSelected(engine); setValues(data.engines[engine] ?? {}); setCaption(data.image_caption); setActiveEngine(data.engine); setError(''); setErrors({}); setResult(null); setReceipt(''); setRevision(value => value + 1)
  }
  async function run(kind: 'save' | 'check' | 'install' | 'download') {
    if (!data || actionLock.current) return
    setError(''); setReceipt('')
    const formFields = fields[selected]
    if (kind === 'save' || kind === 'check' || (kind === 'download' && selected === 'mineru')) {
      const invalid = validateSettings(formFields, values)
      if (values.model_download_endpoint) {
        try { if (!['http:', 'https:'].includes(new URL(String(values.model_download_endpoint)).protocol)) invalid.model_download_endpoint = '请输入 http 或 https 地址' }
        catch { invalid.model_download_endpoint = '请输入完整镜像地址' }
      }
      if (Object.keys(invalid).length) { setErrors(invalid); setError('请修正表单中的错误'); return }
    }
    actionLock.current = true; setBusy(kind)
    try {
      const payload = settingsPayload(formFields, values)
      if (kind === 'save') {
        const response = await saveParsingSettings(selected, payload, caption, activeEngine)
        setData(response); setValues(response.engines[selected] ?? {}); setActiveEngine(response.engine); setCaption(response.image_caption); setRevision(value => value + 1); setResult(null)
        setReceipt('解析配置已保存，仅作用于后续解析。已有文档不会自动重新解析。')
      } else if (kind === 'check') {
        const response = selected === 'mineru' ? await checkMineru(payload)
          : selected === 'docling' && values.mode === 'remote' ? await checkDocling(String(values.api_base_url ?? ''), values.api_token)
          : selected === 'tika' ? await checkTika(String(values.server_url ?? ''))
          : await checkParser(selected)
        setResult(response)
      } else {
        if (kind === 'install' && (!installable.has(selected) || !data.installable.includes(selected))) throw new Error('此解析器没有后端安装入口')
        if ((selected === 'mineru' ? mineruRunning : genericRunning) !== false) throw new Error('请先确认任务状态，当前任务可能仍在运行')
        const response = kind === 'install' ? await installParser(selected)
          : selected === 'mineru' ? await downloadMineruModels({ model_type: modelType, source: values.model_download_source === 'modelscope' ? 'modelscope' : 'huggingface', endpoint: String(values.model_download_endpoint ?? ''), local_cli_path: String(values.local_cli_path ?? '') })
          : selected === 'docling' && data.model_downloadable.includes('docling') ? await downloadParserModels('docling')
          : { ok: false, message: '此解析器没有后端模型下载入口' }
        setJobRefresh(value => value + 1)
        if (!response.ok) throw new Error(response.message || '任务未启动，请重试')
        if (selected === 'mineru') setMineruRunning(true); else setGenericRunning(true)
        setReceipt('后端已接受任务启动。真实状态与日志见下方；此操作未保存表单配置。')
      }
    } catch (error) { setError(settingsError(error)) }
    finally { actionLock.current = false; setBusy('') }
  }
  if (loading) return <p role="status" className="settings-note">正在读取文档解析配置…</p>
  if (loadError || !data) return <div role="alert" className="settings-error">{loadError || '后端未返回解析配置'}<button type="button" className="settings-button-secondary ml-2" onClick={() => setAttempt(value => value + 1)}>重试读取</button></div>
  const entry = data.available_engines.find(item => item.id === selected)
  const readiness = data.readiness[selected]
  const supportsInstall = installable.has(selected) && data.installable.includes(selected)
  const supportsDownload = selected === 'mineru' || (selected === 'docling' && data.model_downloadable.includes('docling'))
  const taskRunning = selected === 'mineru' ? mineruRunning : genericRunning
  return <div className="min-w-0 space-y-5">
    <div><h2 className="text-xl font-semibold text-slate-900">文档解析</h2><p className="settings-note mt-2">直接保存并作用于后续文档，不经过模型草稿。扫描 PDF 仍可能使用 MinerU Cloud OCR，数据可能发送到云端；选择本地解析器不代表全程本地处理。</p></div>
    <nav aria-label="文档解析器列表" className="flex flex-wrap gap-2">{Object.entries(parserNames).map(([engine, name]) => <button type="button" key={engine} disabled={Boolean(busy)} aria-pressed={engine === selected} onClick={() => changeParser(engine as ParserEngine)} className={`rounded-xl border px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-blue-600 ${engine === selected ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600'}`}>{name}</button>)}</nav>
    <section className="settings-card min-w-0 space-y-5" aria-label="当前解析器配置">
      <h3 className="text-lg font-semibold">{parserNames[selected]}</h3>
      <p className="settings-note">{entry?.description || '后端未提供此解析器描述。'}</p>
      <p className="settings-note">依赖状态：{entry ? entry.available ? '可用' : '不可用' : '后端未报告'}；准备状态：{readiness ? readiness.ready ? '前置条件满足' : `未就绪${readiness.message ? `：${readiness.message}` : ''}` : '未知'}。实际运行仍可能因资源、网络或权限失败。</p>
      {(selected === 'mineru' || selected === 'docling') && <p className="settings-note">远端凭据：{data[selected].api_token_set ? '已保存（不回显）' : '未保存'}。未编辑时保留原值；只有明确选择清除才应清空。</p>}
      {selected === 'text_only' && <p className="settings-note">内置文本提取没有独立参数，无需安装或下载模型，不提供版面结构恢复。</p>}
      {capabilityError && <p className="settings-error" role="alert">{capabilityError}</p>}
      {error && <p className="settings-error" role="alert">{error}</p>}
      {receipt && <p role="status" className="text-sm text-blue-700">{receipt}</p>}
      <form noValidate className="space-y-5" onSubmit={event => { event.preventDefault(); void run('save') }}>
        <fieldset disabled={Boolean(busy)} className="grid gap-4 sm:grid-cols-2">
          <label className="settings-label">后续解析使用的解析器<select className="settings-input mt-2" value={activeEngine} onChange={event => { setActiveEngine(event.target.value as ParserEngine); setReceipt(''); setResult(null) }}>{Object.entries(parserNames).map(([engine, name]) => <option key={engine} value={engine}>{name}</option>)}</select></label>
          <label className="settings-label flex items-center gap-3"><input type="checkbox" checked={caption} onChange={event => { setCaption(event.target.checked); setReceipt(''); setResult(null) }} className="h-5 w-5 accent-blue-600" />使用视觉模型为嵌入图片生成描述</label>
        </fieldset>
        <EngineParsingFields key={`${selected}-${revision}`} fields={fields[selected]} values={values} onChange={edit} errors={errors} disabled={Boolean(busy)} />
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" className="settings-button" disabled={Boolean(busy) || !dirty}>{busy === 'save' ? '正在保存…' : '保存当前解析配置'}</button>
          <button type="button" className="settings-button-secondary" disabled={Boolean(busy)} onClick={() => void run('check')}>{busy === 'check' ? '正在检查…' : '检查解析器'}</button>
          {dirty && <span className="settings-note">有未保存修改</span>}
        </div>
      </form>
      <p className="settings-note">{selected === 'mineru' || selected === 'tika' || (selected === 'docling' && values.mode === 'remote') ? '此检查使用当前表单连接参数，不保存配置。' : '此检查使用后端已保存参数与当前依赖状态，不保存当前表单。'}</p>
      <SettingsCheckResult result={result} />
      {(supportsInstall || supportsDownload) && <fieldset disabled={Boolean(busy)} className="space-y-3 border-t border-slate-100 pt-4">
        <legend className="settings-label">安装与模型下载（独立操作）</legend>
        <p className="settings-note">启动将实际安装依赖或下载模型。共用任务互斥运行，不排队；不保存解析配置。下载后可重新检查就绪状态。</p>
        {selected === 'mineru' && <label className="settings-label block">下载的模型类型<select className="settings-input mt-2" value={modelType} onChange={event => setModelType(event.target.value as MineruDownloadRequest['model_type'])}><option value="pipeline">pipeline</option><option value="vlm">vlm</option><option value="all">all</option></select><span className="settings-note">使用本表单的下载来源、镜像与 CLI 路径。</span></label>}
        <div className="flex flex-wrap gap-3">
          {supportsInstall && <button type="button" className="settings-button-secondary" disabled={genericRunning !== false} onClick={() => void run('install')}>{busy === 'install' ? '正在启动安装…' : '安装此解析器依赖'}</button>}
          {supportsDownload && <button type="button" className="settings-button-secondary" disabled={taskRunning !== false} onClick={() => void run('download')}>{busy === 'download' ? '正在启动下载…' : '下载模型'}</button>}
        </div>
        {taskRunning !== false && <p className="settings-note">{taskRunning ? '当前单例任务进行中，请查看下方状态。' : '正在确认当前任务状态，确认后才能启动新任务。'}</p>}
      </fieldset>}
    </section>
    <div className="grid min-w-0 gap-4 2xl:grid-cols-2">
      <ParsingTaskMonitor scope="generic" refresh={jobRefresh} onRunningChange={setGenericRunning} />
      <ParsingTaskMonitor scope="mineru" refresh={jobRefresh} onRunningChange={setMineruRunning} />
    </div>
  </div>
}
