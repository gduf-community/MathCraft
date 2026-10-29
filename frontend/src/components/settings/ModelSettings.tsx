import { Bot, Database, SlidersHorizontal } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { ModelWriteReadbackError, deleteDirectModel, readLiveModelSettings, readDirectModelDraft, saveDirectModel, setDefaultDirectModel, setDirectTaskMode } from '../../api/modelSettings'
import type { DirectModelResponse, DirectModelTarget, ModelCatalog, ModelDraft, ModelEntry, ModelServiceName, ModelSettingsResponse } from '../../types/modelSettings'
import { equal, safeError } from './model/catalog'
import { changedDirectModels, directServices, editableCatalog, findDirectModel, mergeDirectEdits, parseDirectHeaders, putDirectModel, removeLocalModel, targetKey, validateDirectModel } from './model/directCatalog'
import { DirectModelEditor } from './model/DirectModelEditor'
import { Field, inputClass, primaryClass, secondaryClass } from './model/Fields'

interface ModelSettingsProps { onDirtyChange?: (dirty: boolean) => void }
const tabs = [
  { value: 'llm', label: '语言模型', icon: Bot },
  { value: 'embedding', label: '嵌入模型', icon: Database },
  { value: 'task', label: '任务模型', icon: SlidersHorizontal },
] as const

export function ModelSettings({ onDirtyChange }: ModelSettingsProps) {
  const [tab, setTab] = useState<ModelServiceName>('llm')
  const [snapshot, setSnapshot] = useState<ModelSettingsResponse | null>(null)
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null)
  const [legacyDraft, setLegacyDraft] = useState<ModelDraft | null>(null)
  const [draftPreview, setDraftPreview] = useState<ModelCatalog | null>(null)
  const [draftError, setDraftError] = useState('')
  const [restoreKey, setRestoreKey] = useState('')
  const [draftSources, setDraftSources] = useState<Record<string, string>>({})
  const [unverified, setUnverified] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [revision, setRevision] = useState(0)
  const [restoreFocus, setRestoreFocus] = useState<DirectModelTarget | null>(null)
  const mounted = useRef(true)
  const requestVersion = useRef(0)
  const lock = useRef(false)
  const id = useId()
  const current = useRef({ catalog, snapshot, draftSources })
  current.current = { catalog, snapshot, draftSources }
  const dirty = !!snapshot && !!catalog && (changedDirectModels(snapshot.catalog, catalog).length > 0 || Object.keys(draftSources).length > 0 || Object.keys(unverified).length > 0)

  useEffect(() => { onDirtyChange?.(dirty) }, [dirty, onDirtyChange])
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange])
  useEffect(() => {
    if (!dirty) return
    const preventLoss = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', preventLoss)
    return () => window.removeEventListener('beforeunload', preventLoss)
  }, [dirty])

  async function load() {
    if (lock.current) return
    const version = ++requestVersion.current
    setBusy('读取模型设置'); setError(''); setNotice('')
    try {
      const [liveResult, draftResult] = await Promise.allSettled([readLiveModelSettings(), readDirectModelDraft()])
      if (!mounted.current || version !== requestVersion.current) return
      if (liveResult.status === 'rejected') throw liveResult.reason
      const data = liveResult.value
      const next = editableCatalog(data.catalog)
      setSnapshot({ ...data, catalog: next }); setCatalog(next)
      setDraftSources({}); setUnverified({}); setRestoreFocus(null); setRestoreKey(''); setRevision((value) => value + 1)
      if (draftResult.status === 'fulfilled') {
        setLegacyDraft(draftResult.value.draft)
        setDraftPreview(draftResult.value.draft?.catalog ?? null)
        setDraftError('')
      } else {
        setLegacyDraft(null); setDraftPreview(null)
        setDraftError('旧草稿暂时无法读取，正式配置仍可正常编辑；可稍后重新读取。')
      }
    } catch (cause) {
      if (mounted.current && version === requestVersion.current) setError(safeError(cause, current.current.catalog ?? undefined))
    } finally {
      if (mounted.current && version === requestVersion.current) setBusy('')
    }
  }
  useEffect(() => {
    mounted.current = true
    void load()
    return () => { mounted.current = false; requestVersion.current += 1 }
  }, [])

  function edit(target: DirectModelTarget, model: ModelEntry) {
    setCatalog((value) => value ? putDirectModel(value, target, model) : value)
    setError(''); setNotice('')
  }
  function clearSource(target: DirectModelTarget) {
    setDraftSources((value) => { const next = { ...value }; delete next[targetKey(target)]; return next })
  }
  function clearUnverified(key: string) {
    setUnverified((value) => { const next = { ...value }; delete next[key]; return next })
  }
  function acceptLive(data: ModelSettingsResponse, completed?: DirectModelTarget) {
    const before = current.current
    if (!before.snapshot || !before.catalog) return
    const nextLive = editableCatalog(data.catalog)
    setCatalog(mergeDirectEdits(before.snapshot.catalog, before.catalog, nextLive, completed))
    setSnapshot({ ...data, catalog: nextLive })
    if (completed) clearSource(completed)
  }
  async function writeAndVerify({ label, action, verify, completed }: {
    label: string
    action: () => Promise<DirectModelResponse>
    verify: (written: ModelCatalog, readback: ModelCatalog) => boolean
    completed?: DirectModelTarget
  }) {
    if (lock.current) return false
    lock.current = true
    setBusy(label); setError(''); setNotice('')
    let wrote = false
    const operationKey = completed ? targetKey(completed) : label
    try {
      const result = await action()
      wrote = true
      if (!result.catalog?.services) throw new Error('写入响应缺少正式目录')
      const readback = await readLiveModelSettings()
      if (!verify(result.catalog, readback.catalog)) throw new Error('正式读回结果与写入响应不一致')
      if (!mounted.current) return false
      acceptLive(readback, completed); clearUnverified(operationKey)
      setNotice(`${label}成功，已读回并核实正式状态。其他配置的本地编辑已保留。`)
      return true
    } catch (cause) {
      if (!mounted.current) return false
      const message = safeError(cause, current.current.catalog ?? undefined)
      if (wrote || cause instanceof ModelWriteReadbackError) {
        const text = `${label}请求已成功，但正式状态待核实：${message}。当前输入已保留，请重新读取核实，或重试当前操作。`
        setUnverified((value) => ({ ...value, [operationKey]: text })); setError(text)
      } else setError(`${label}失败：${message}。当前输入与其他本地编辑均已保留。`)
      return false
    } finally { lock.current = false; if (mounted.current) setBusy('') }
  }
  async function save(target: DirectModelTarget, model: ModelEntry) {
    if (!current.current.snapshot) return false
    const validation = validateDirectModel(current.current.snapshot.catalog, target, model)
    if (validation) { setError(validation); return false }
    const config = model.direct_config!
    const parsedHeaders = parseDirectHeaders(config.extra_headers)
    if (parsedHeaders.error !== null) { setError(parsedHeaders.error); return false }
    const normalized: ModelEntry = {
      ...model, name: model.name!.trim(), model: model.model.trim(),
      direct_config: { ...config, extra_headers: parsedHeaders.headers },
    }
    const draftUpdatedAt = current.current.draftSources[targetKey(target)]
    return writeAndVerify({
      label: '保存并启用', completed: target,
      action: () => saveDirectModel({ service: target.service, profile_id: target.profile_id, model: normalized, ...(draftUpdatedAt ? { restore_draft: true, draft_updated_at: draftUpdatedAt } : {}) }),
      verify: (written, readback) => {
        const saved = findDirectModel(written, target)
        const confirmed = findDirectModel(readback, target)
        return !!saved && !!confirmed && saved.name === normalized.name && saved.model === normalized.model && equal(saved, confirmed) &&
          written.services[target.service]?.active_profile_id === readback.services[target.service]?.active_profile_id &&
          written.services[target.service]?.active_model_id === readback.services[target.service]?.active_model_id &&
          (target.service !== 'task' || written.services.task?.mode === readback.services.task?.mode)
      },
    })
  }
  function makeDefault(target: DirectModelTarget) {
    void writeAndVerify({ label: '设为默认', action: () => setDefaultDirectModel(target), verify: (_written, readback) => readback.services[target.service]?.active_profile_id === target.profile_id && readback.services[target.service]?.active_model_id === target.model_id })
  }
  function changeMode(mode: 'inherit' | 'profiles') {
    void writeAndVerify({ label: mode === 'inherit' ? '跟随主模型' : '启用独立任务配置', action: () => setDirectTaskMode(mode), verify: (_written, readback) => (readback.services.task?.mode ?? 'inherit') === mode })
  }
  function reset(target: DirectModelTarget) {
    const state = current.current
    if (!state.catalog || !state.snapshot || !window.confirm('撤销当前配置的本地编辑？其他配置的编辑会保留。')) return
    const original = findDirectModel(state.snapshot.catalog, target)
    setCatalog(original ? putDirectModel(state.catalog, target, original) : removeLocalModel(state.catalog, target))
    clearSource(target); clearUnverified(targetKey(target)); setError(''); setNotice('已撤销当前项本地编辑。')
  }
  function discardNew(target: DirectModelTarget) {
    if (lock.current) return
    const original = current.current.snapshot?.catalog
    const saved = original ? findDirectModel(original, target) : undefined
    setCatalog((value) => {
      if (!value) return value
      if (saved) return putDirectModel(value, target, saved)
      const next = removeLocalModel(value, target)
      const service = next.services[target.service]
      if (!service || original?.services[target.service]?.profiles.some((profile) => profile.id === target.profile_id)) return next
      return { ...next, services: { ...next.services, [target.service]: {
        ...service, profiles: service.profiles.filter((profile) => profile.id !== target.profile_id || profile.models.length > 0),
      } } }
    })
    clearSource(target)
    const key = targetKey(target)
    if (unverified[key]) {
      const message = '已关闭新增面板；此前保存请求已成功，但正式状态仍待核实，请重新读取正式目录。关闭仅丢弃本地输入，不会删除已保存的模型。'
      setUnverified((value) => ({ ...value, [key]: message })); setError(message)
    } else setError('')
    setNotice('')
  }
  function remove(target: DirectModelTarget) {
    const state = current.current
    if (!state.snapshot || !state.catalog) return
    const existing = findDirectModel(state.snapshot.catalog, target)
    if (!existing) {
      if (!window.confirm('取消添加并放弃当前配置的输入？')) return
      setCatalog(removeLocalModel(state.catalog, target)); clearSource(target); clearUnverified(targetKey(target)); return
    }
    if (!window.confirm(`删除配置「${existing.name || existing.model}」？如果它仍被知识库等引用，服务端将拒绝删除。当前项的本地编辑也将丢弃。`)) return
    void writeAndVerify({ label: '删除配置', completed: target, action: () => deleteDirectModel(target), verify: (written, readback) => !findDirectModel(written, target) && !findDirectModel(readback, target) })
  }
  const recoveryRows = draftPreview ? directServices.flatMap((service) => editableCatalog(draftPreview).services[service]?.profiles.flatMap((profile) => profile.models.map((model) => ({ target: { service, profile_id: profile.id, model_id: model.id }, model }))) ?? []) : []
  function restore() {
    const row = recoveryRows.find(({ target }) => targetKey(target) === restoreKey)
    if (!row || !catalog || !legacyDraft?.updated_at) return
    const currentModel = findDirectModel(catalog, row.target)
    const original = snapshot ? findDirectModel(snapshot.catalog, row.target) : undefined
    if (currentModel && (!equal(currentModel, original) || draftSources[restoreKey]) && !window.confirm('恢复此项会替换该配置当前的本地输入，其他配置不变，是否继续？')) return
    edit(row.target, row.model)
    setDraftSources((value) => ({ ...value, [restoreKey]: legacyDraft.updated_at! }))
    setTab(row.target.service); setRestoreFocus({ ...row.target })
    setNotice('已恢复所选配置的旧草稿输入，尚未启用。请核对后保存当前项；凭据将仅从所选草稿版本恢复。')
  }
  if (!snapshot || !catalog) return <section className="space-y-4" aria-label="模型与服务设置">
    <p role="status" className="text-sm text-slate-500">{busy || '模型设置尚未读取'}</p>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {!busy && <button type="button" className={primaryClass} onClick={() => void load()}>重新读取模型设置</button>}
  </section>
  const migration = snapshot.migration ?? snapshot.catalog.direct_config_migration
  const draftRenamed = draftPreview?.direct_config_migration?.renamed
  return <section className="min-w-0 space-y-5" aria-label="模型与服务设置" aria-busy={!!busy}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-lg font-semibold text-slate-800">模型与服务</h2><p className="mt-1 text-sm leading-6 text-slate-500">每项独立配置提供方、地址与凭据，一次保存并启用。保存不会自动获取模型列表。</p></div>
      <button type="button" className={secondaryClass} disabled={!!busy} onClick={() => { if (!dirty || window.confirm('重新读取会替换所有未保存输入及草稿恢复来源；已成功写入但待核实的操作也将从正式目录读取。是否继续？')) void load() }}>重新读取</button>
    </div>
    {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm leading-6 text-red-800">{error}</p>}
    {notice && <p role="status" className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm leading-6 text-blue-800">{notice}</p>}
    {Object.keys(unverified).length > 0 && !error && <p role="status" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">有已写入但正式状态待核实的操作。输入仍保留，请重新读取正式目录核实。</p>}
    {migration && <details className="rounded-xl border border-blue-200 bg-blue-50 p-3" open={!!migration.renamed?.length}>
      <summary className="cursor-pointer text-sm font-medium text-blue-800 focus-visible:outline-2 focus-visible:outline-blue-500">旧模型配置迁移信息</summary>
      <p className="mt-2 text-sm leading-6 text-blue-800">{safeError(new Error(migration.message || '旧共享连接已展开为各模型的独立配置；旧草稿仍需明确恢复后逐项保存。'), catalog)}</p>
      {!!migration.renamed?.length && <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-blue-800">{migration.renamed.map((entry, index) => <li key={JSON.stringify([entry.service, entry.profile_id, entry.model_id, index])}>{entry.old_name ?? entry.from ?? '未命名'} → {entry.new_name ?? entry.to}</li>)}</ul>}
    </details>}
    {draftError && <p role="status" className="text-sm text-amber-800">{draftError}</p>}
    {legacyDraft?.catalog && <details className="settings-card rounded-xl border border-amber-200 bg-amber-50 p-3">
      <summary className="cursor-pointer text-sm font-medium text-amber-800 focus-visible:outline-2 focus-visible:outline-blue-500">保留的旧草稿：按配置项恢复</summary>
      <div className="mt-3 space-y-3">
        <p className="text-sm leading-6 text-amber-800">旧草稿尚未启用。选择一个配置载入表单，再单独保存；这不会应用整份草稿，也不会改变其他配置。{legacyDraft.updated_at ? `草稿版本：${legacyDraft.updated_at}` : '缺少草稿版本，暂时无法安全恢复。'}</p>
        {!!draftRenamed?.length && <div className="text-sm text-amber-800"><p>旧草稿的配置名称调整：</p><ul className="mt-2 list-inside list-disc space-y-1">{draftRenamed.map((entry, index) => <li key={JSON.stringify([entry.service, entry.model_id, index])}>{entry.old_name || "未命名"} → {entry.new_name}</li>)}</ul></div>}
        <Field label="选择恢复的配置"><select className={inputClass} value={restoreKey} onChange={(event) => setRestoreKey(event.target.value)}><option value="">请选择旧草稿中的配置</option>{recoveryRows.map(({ target, model }) => <option key={targetKey(target)} value={targetKey(target)}>{tabs.find((entry) => entry.value === target.service)?.label} · {model.name || model.model || model.id}</option>)}</select></Field>
        <button type="button" className={secondaryClass} disabled={!!busy || !restoreKey || !legacyDraft.updated_at} onClick={restore}>恢复所选项到表单</button>
      </div>
    </details>}
    <div className="settings-card min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <div role="tablist" aria-label="模型类别" className="flex overflow-x-auto border-b border-slate-200 px-2 pt-2">
        {tabs.map(({ value, label, icon: Icon }, index) => <button key={value} type="button" role="tab" id={`${id}-tab-${value}`} aria-controls={`${id}-panel-${value}`} aria-selected={tab === value} tabIndex={tab === value ? 0 : -1}
          className={`flex min-h-11 shrink-0 items-center gap-2 rounded-t-xl border-b-2 px-4 py-3 text-sm focus-visible:outline-2 focus-visible:outline-blue-500 ${tab === value ? 'border-blue-600 bg-blue-50 font-semibold text-blue-700' : 'border-transparent text-slate-500 hover:bg-slate-50 hover:text-slate-700'}`}
          onClick={() => setTab(value)} onKeyDown={(event) => {
            let next = index
            if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
            else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length
            else if (event.key === 'Home') next = 0
            else if (event.key === 'End') next = tabs.length - 1
            else return
            event.preventDefault(); setTab(tabs[next].value); document.getElementById(`${id}-tab-${tabs[next].value}`)?.focus()
          }}><Icon size={16} aria-hidden="true" />{label}</button>)}
      </div>
      <div className="min-w-0 p-4 sm:p-5">{tabs.map(({ value }) => <div key={value} role="tabpanel" hidden={tab !== value} id={`${id}-panel-${value}`} aria-labelledby={`${id}-tab-${value}`}>
        <DirectModelEditor key={`${value}/${revision}`} catalog={catalog} live={snapshot.catalog} service={value} providers={snapshot.providers[value] ?? (value === 'task' ? snapshot.providers.llm ?? [] : [])}
          busy={!!busy} error={error} active={tab === value} requestedSelection={restoreFocus} draftSources={draftSources} unverified={unverified} onChange={edit} onSave={save} onDiscardNew={discardNew} onDelete={remove} onDefault={makeDefault} onMode={changeMode} onReset={reset} />
      </div>)}</div>
    </div>
    <p role="status" className="text-xs leading-5 text-slate-500">{busy ? `${busy}中…` : dirty ? '有未保存或待核实的配置；切换类别会保留输入，刷新或离开前将提醒。' : '当前正式配置已读取。保存与默认选择是独立操作。'}</p>
  </section>
}
