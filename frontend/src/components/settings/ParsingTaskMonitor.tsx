import { useEffect, useRef, useState } from 'react'
import { cancelParsingJob, getParsingJob } from '../../api/parsingSettings'
import type { ParsingJobScope, ParsingJobStatus } from '../../types/parsingSettings'
import { settingsError } from './EngineParsingFields'

const stateLabels: Record<ParsingJobStatus['state'], string> = { idle: '当前无任务', running: '进行中', done: '已完成', failed: '失败', cancelled: '已取消' }
const POLL_INTERVAL = 1500
const LOG_LIMIT = 400
export function ParsingTaskMonitor({ scope, refresh, onRunningChange }: { scope: ParsingJobScope; refresh: number; onRunningChange: (running: boolean | null) => void }) {
  const [status, setStatus] = useState<ParsingJobStatus | null>(null)
  const [lines, setLines] = useState<[number, string][]>([])
  const [error, setError] = useState('')
  const [cancelError, setCancelError] = useState('')
  const [cancelling, setCancelling] = useState(false)
  const [cancelRequested, setCancelRequested] = useState(false)
  const [retry, setRetry] = useState(0)
  const callback = useRef(onRunningChange)
  callback.current = onRunningChange
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    let cursor = 0
    let previous: ParsingJobStatus | null = null
    let polls = 0
    let buffer = new Map<number, string>()
    async function poll() {
      try {
        const requestedCursor = polls % 8 === 0 ? 0 : cursor
        let data = await getParsingJob(scope, requestedCursor)
        if (!active) return
        const newTask = data.state === 'running' && previous !== null && (previous.state !== 'running' || previous.kind !== data.kind || previous.engine !== data.engine)
        if (data.next_cursor < cursor || newTask) {
          data = await getParsingJob(scope, 0)
          if (!active) return
          buffer = new Map()
        } else if (requestedCursor === 0) buffer = new Map()
        const start = data.next_cursor - data.lines.length
        for (const [index, line] of data.lines.entries()) buffer.set(start + index, line)
        if (data.state === 'idle') buffer.clear()
        const visible = [...buffer.entries()].sort(([left], [right]) => left - right).slice(-LOG_LIMIT)
        buffer = new Map(visible)
        cursor = data.next_cursor; polls += 1; previous = data
        setStatus(data); setLines(visible); setError('')
        if (newTask || data.state !== 'running') setCancelRequested(false)
        callback.current(data.state === 'running')
      } catch (error) {
        if (!active) return
        setError(`任务状态暂时未知：${settingsError(error)}。下次读取将重新对齐服务状态。`)
        callback.current(null); cursor = 0; polls = 0; buffer = new Map(); previous = null
      }
      if (active) timer = setTimeout(() => { void poll() }, POLL_INTERVAL)
    }
    void poll()
    return () => { active = false; clearTimeout(timer) }
  }, [scope, refresh, retry])
  const cancelLock = useRef(false)
  async function cancel() {
    if (cancelLock.current || cancelRequested) return
    cancelLock.current = true; setCancelling(true); setCancelError('')
    try {
      const result = await cancelParsingJob(scope)
      if (!result.ok) throw new Error(result.message || '取消失败，请重试')
      setCancelRequested(true); setRetry(value => value + 1)
    } catch (error) { setCancelError(settingsError(error)) }
    finally { cancelLock.current = false; setCancelling(false) }
  }
  return <section className="settings-card min-w-0 space-y-3" aria-label={scope === 'mineru' ? 'MinerU 下载任务' : '解析器安装与 Docling 下载任务'}>
    <h3 className="font-semibold text-slate-900">{scope === 'mineru' ? 'MinerU 模型下载' : '解析器安装／Docling 模型下载'}</h3>
    <p className="settings-note">后端进程内单例。刷新可继续观察当前任务；服务重启后不恢复任务。取消不回滚已安装或下载内容。</p>
    <p role="status" className="text-sm">{error ? '当前状态未知' : status ? stateLabels[status.state] : '正在读取状态…'}{!error && status?.engine ? ` · ${status.engine}` : ''}{!error && status?.kind ? ` · ${status.kind === 'install' ? '依赖安装' : '模型下载'}` : ''}</p>
    {status?.message && !error && <p className={status.state === 'failed' ? 'settings-error' : 'settings-note'}>{status.message}</p>}
    {error && <p className="settings-error" role="alert">{error}</p>}
    {cancelError && <p className="settings-error" role="alert">{cancelError}</p>}
    {cancelRequested && <p role="status" className="settings-note">取消请求已提交，正在等待后端确认终态。</p>}
    <div className="flex flex-wrap gap-3">
      <button type="button" className="settings-button-secondary" onClick={() => setRetry(value => value + 1)}>重新读取状态</button>
      <button type="button" className="settings-button-secondary" disabled={Boolean(error) || status?.state !== 'running' || cancelling || cancelRequested} onClick={() => void cancel()}>{cancelling ? '正在请求取消…' : cancelRequested ? '等待取消结果…' : '取消当前任务'}</button>
    </div>
    <details open={lines.length > 0}><summary className="cursor-pointer text-sm text-slate-600">当前日志（最多显示最近 {LOG_LIMIT} 行）</summary>
      {error && <p className="settings-note">以下是上次读取的日志。</p>}
      <pre tabIndex={0} aria-label="任务日志" className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-xl bg-slate-50 p-3 text-xs text-slate-700">{lines.length ? lines.map(([, line]) => line).join('\n') : '暂无日志'}</pre>
    </details>
  </section>
}
