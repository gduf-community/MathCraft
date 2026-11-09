import { Loader2 } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { getModelSettings, saveModelSettings, testDeepSeek, testMinerU } from '../../../api/modelSettings'
import type { ModelSettings } from '../../../api/modelSettings'

interface PersonalModelSettingsProps {
  onDirtyChange?: (dirty: boolean) => void
}

/** 个人中心和设置页共用个人凭据编辑；测试只验证服务端已保存的配置。 */
export function PersonalModelSettings({ onDirtyChange }: PersonalModelSettingsProps) {
  const [model, setModel] = useState<ModelSettings | null>(null)
  const [deepseekKey, setDeepseekKey] = useState('')
  const [mineruToken, setMineruToken] = useState('')
  const [clearDeepseek, setClearDeepseek] = useState(false)
  const [clearMineru, setClearMineru] = useState(false)
  const [busy, setBusy] = useState<'load' | 'save' | 'deepseek' | 'mineru' | null>('load')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const lock = useRef(false)
  const mounted = useRef(false)
  const id = useId()
  const dirty = deepseekKey !== '' || mineruToken !== '' || clearDeepseek || clearMineru
  const disabled = busy !== null || model === null

  useEffect(() => { onDirtyChange?.(dirty) }, [dirty, onDirtyChange])
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange])
  useEffect(() => {
    if (!dirty) return
    const preventLoss = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', preventLoss)
    return () => window.removeEventListener('beforeunload', preventLoss)
  }, [dirty])

  const load = useCallback(async () => {
    if (lock.current) return
    lock.current = true
    setBusy('load')
    setError('')
    try {
      const fresh = await getModelSettings()
      if (mounted.current) setModel(fresh)
    } catch {
      if (mounted.current) setError('模型配置读取失败，请重试。')
    } finally {
      lock.current = false
      if (mounted.current) setBusy(null)
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    void load()
    return () => { mounted.current = false }
  }, [load])

  const save = async () => {
    if (lock.current || !model || !dirty) return
    if ((!clearDeepseek && deepseekKey !== '' && !deepseekKey.trim()) ||
      (!clearMineru && mineruToken !== '' && !mineruToken.trim())) {
      setError('凭据不能仅含空格；如需删除，请勾选清除个人凭据。')
      return
    }
    lock.current = true
    setBusy('save')
    setError('')
    setNotice('')
    try {
      await saveModelSettings({
        ...(clearDeepseek ? { deepseek_api_key: '' } : deepseekKey.trim() ? { deepseek_api_key: deepseekKey.trim() } : {}),
        ...(clearMineru ? { mineru_token: '' } : mineruToken.trim() ? { mineru_token: mineruToken.trim() } : {}),
      })
      setDeepseekKey('')
      setMineruToken('')
      setClearDeepseek(false)
      setClearMineru(false)
      // 写入已确认后，读回失败需明确提示，不能以旧状态继续测试。
      setModel(null)
      try {
        setModel(await getModelSettings())
        setNotice('模型配置已保存。现在可以测试已保存的配置。')
      } catch {
        setError('保存已完成，但最新配置读取失败。请重新读取后再测试。')
      }
    } catch {
      setError('模型配置保存未获确认，请重试；当前输入已保留。')
    } finally {
      lock.current = false
      setBusy(null)
    }
  }

  const test = async (service: 'deepseek' | 'mineru') => {
    if (lock.current || !model) return
    if (dirty) {
      setError('请先保存当前修改，再测试已保存的配置。')
      return
    }
    lock.current = true
    setBusy(service)
    setError('')
    setNotice('')
    try {
      if (service === 'deepseek') await testDeepSeek()
      else await testMinerU()
      setNotice(`${service === 'deepseek' ? 'DeepSeek' : 'MinerU'} 已保存配置连接测试通过（含服务端默认配置）。`)
    } catch {
      setError('已保存配置测试失败，请检查凭据或服务可用性。')
    } finally {
      lock.current = false
      setBusy(null)
    }
  }

  const inputClass = 'block w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-primary disabled:opacity-60'
  const buttonClass = 'rounded-lg border border-line px-3 py-2 text-sm text-ink-2 hover:border-primary disabled:opacity-50'
  const edit = (change: () => void) => { change(); setNotice(''); setError('') }

  return <section className="mb-4 rounded-xl border border-line/70 bg-white p-5" aria-labelledby={`${id}-title`}>
    <div className="mb-4 flex items-center justify-between gap-3">
      <h3 id={`${id}-title`} className="text-sm font-bold text-ink">个人模型配置</h3>
      <button type="button" onClick={() => void save()} disabled={disabled || !dirty}
        className="rounded-lg bg-primary px-3.5 py-2 text-sm font-semibold text-white disabled:opacity-50">
        {busy === 'save' ? '保存中…' : '保存配置'}
      </button>
    </div>
    <p className="mb-3 text-sm text-ink-2">留空表示保留原凭据；勾选清除后点击保存。测试只使用已保存的配置，请先保存修改。</p>
    {busy === 'load' && <p role="status" className="mb-3 text-sm"><Loader2 size={14} className="mr-2 inline animate-spin" />正在读取配置…</p>}
    {error && <p role="alert" className="mb-3 text-sm text-red-600">{error}</p>}
    {notice && <p role="status" className="mb-3 text-sm text-ink-2">{notice}</p>}
    {!model && busy === null && <button type="button" className={buttonClass} onClick={() => void load()}>重新读取配置</button>}
    <div className="space-y-4">
      <fieldset disabled={disabled} className="space-y-2 rounded-xl border border-line p-3">
        <legend className="px-1 text-sm font-semibold">{model?.deepseek_model ?? 'DeepSeek'}</legend>
        <p className="text-xs text-ink-3">{model ? model.deepseek_key_configured ? `已配置个人 Key ${model.deepseek_key_masked ?? ''}` : '未配置个人 Key' : '配置尚未读取'}</p>
        <label htmlFor={`${id}-deepseek`} className="block text-sm">新的 DeepSeek API Key</label>
        <input id={`${id}-deepseek`} type="password" autoComplete="new-password" value={deepseekKey} disabled={disabled || clearDeepseek}
          onChange={(event) => edit(() => setDeepseekKey(event.target.value))} className={inputClass} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={clearDeepseek} onChange={(event) => edit(() => { setClearDeepseek(event.target.checked); setDeepseekKey('') })} />
          清除个人 DeepSeek Key
        </label>
        <p className="text-xs text-ink-3">清除后服务端可能使用系统默认 Key；没有默认 Key 时服务不可用。</p>
        <button type="button" className={buttonClass} disabled={disabled || dirty} onClick={() => void test('deepseek')}>
          {busy === 'deepseek' ? '测试中…' : '测试已保存配置'}
        </button>
      </fieldset>
      <fieldset disabled={disabled} className="space-y-2 rounded-xl border border-line p-3">
        <legend className="px-1 text-sm font-semibold">MinerU OCR</legend>
        <p className="text-xs text-ink-3">{model ? model.mineru_token_configured ? `已配置个人 Token ${model.mineru_token_masked ?? ''}` : '使用系统默认 Token（可用性以测试为准）' : '配置尚未读取'}</p>
        <label htmlFor={`${id}-mineru`} className="block text-sm">新的 MinerU Token</label>
        <input id={`${id}-mineru`} type="password" autoComplete="new-password" value={mineruToken} disabled={disabled || clearMineru}
          onChange={(event) => edit(() => setMineruToken(event.target.value))} className={inputClass} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={clearMineru} onChange={(event) => edit(() => { setClearMineru(event.target.checked); setMineruToken('') })} />
          清除个人 MinerU Token，使用系统默认 Token
        </label>
        {model && <p className="text-xs text-ink-3">单文件 ≤ {model.mineru_limits.max_file_mb} MB，页数 ≤ {model.mineru_limits.max_pages} 页</p>}
        <button type="button" className={buttonClass} disabled={disabled || dirty} onClick={() => void test('mineru')}>
          {busy === 'mineru' ? '测试中…' : '测试已保存配置'}
        </button>
      </fieldset>
      {dirty && <p role="status" className="text-sm text-ink-2">有未保存的修改，请先保存再测试。</p>}
      {model && <div className="rounded-xl border border-dashed border-line bg-page/60 p-3 text-xs text-ink-3">
        <p>系统内置向量模型：{model.embedding_model}（不可配置）</p>
        <p className="mt-1">系统内置重排模型：{model.rerank_model}（不可配置）</p>
      </div>}
    </div>
  </section>
}
