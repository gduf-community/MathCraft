/** 文档预览专属传输：有界文本、认证 PDF Blob 与窗口生命周期。 */
import {
  ApiError,
  assertCurrentSession,
  getSessionGeneration,
  onSessionCleared,
  sessionFetch,
} from './session'

export type TextDocumentFormat = 'MD' | 'TXT'
const TEXT_LIMIT_BYTES = 2 * 1024 * 1024
const TEXT_TIMEOUT_MS = 60_000
const PDF_TIMEOUT_MS = 180_000

function documentPath(bankId: string, docId: string, inline: boolean): string {
  return `/api/banks/${encodeURIComponent(bankId)}/documents/${encodeURIComponent(docId)}/download${inline ? '?inline=1' : ''}`
}

/** 主动关闭、切换文档或注销不作为预览错误向用户报告。 */
export function isDocumentPreviewCancelled(error: unknown): boolean {
  return (error instanceof DOMException && error.name === 'AbortError')
    || (error instanceof ApiError && error.code === 'SESSION_ENDED')
}

/** 超时涵盖认证、响应头与响应体；外部取消贯通到 sessionFetch。 */
async function readDocument<T>(
  bankId: string,
  docId: string,
  timeout: number,
  signal: AbortSignal | undefined,
  consume: (response: Response, signal: AbortSignal) => Promise<T>,
  inline = true,
): Promise<T> {
  const started = getSessionGeneration()
  const controller = new AbortController()
  const cancel = () => controller.abort(new DOMException('预览已取消', 'AbortError'))
  const unsubscribe = onSessionCleared(cancel)
  signal?.addEventListener('abort', cancel, { once: true })
  if (signal?.aborted) cancel()
  const timer = window.setTimeout(() => controller.abort(new ApiError(
    `文档请求超时（${timeout / 1000} 秒），请重试或下载文档`, 'DOCUMENT_TIMEOUT',
  )), timeout)
  const rejectAborted = () => rejectCancellation(controller.signal.reason)
  let rejectCancellation: (reason: unknown) => void = () => {}
  const cancelled = new Promise<never>((_resolve, reject) => { rejectCancellation = reject })
  controller.signal.addEventListener('abort', rejectAborted, { once: true })
  try {
    controller.signal.throwIfAborted()
    return await Promise.race([cancelled, (async () => {
      const response = await sessionFetch(documentPath(bankId, docId, inline), { signal: controller.signal })
      controller.signal.throwIfAborted()
      assertCurrentSession(started)
      if (!response.ok) {
        await response.body?.cancel()
        throw new ApiError(`文档请求失败（HTTP ${response.status}），请重试或下载文档`, 'DOCUMENT_HTTP_ERROR', response.status)
      }
      const result = await consume(response, controller.signal)
      controller.signal.throwIfAborted()
      assertCurrentSession(started)
      return result
    })()])
  } finally {
    window.clearTimeout(timer)
    unsubscribe()
    signal?.removeEventListener('abort', cancel)
    controller.signal.removeEventListener('abort', rejectAborted)
    controller.abort()
  }
}

/** UTF-8 文本预览，最多 2 MiB；兼容旧调用，默认按 MD 校验媒体类型。 */
export async function fetchDocumentText(
  bankId: string,
  docId: string,
  signal?: AbortSignal,
  docFormat: TextDocumentFormat = 'MD',
): Promise<string> {
  return readDocument(bankId, docId, TEXT_TIMEOUT_MS, signal, async (response, requestSignal) => {
    const contentType = response.headers.get('Content-Type') ?? ''
    const mediaType = contentType.split(';')[0].trim().toLowerCase()
    const allowed = docFormat === 'TXT' ? ['text/plain'] : ['text/plain', 'text/markdown', 'text/x-markdown']
    const charset = /charset\s*=\s*["']?([^;\s"']+)/i.exec(contentType)?.[1].toLowerCase()
    if (!allowed.includes(mediaType) || (charset && charset !== 'utf-8' && charset !== 'utf8')) {
      await response.body?.cancel()
      throw new ApiError('文档内容类型与文本预览不匹配，请下载文档查看', 'DOCUMENT_CONTENT_TYPE')
    }
    const declaredLength = Number(response.headers.get('Content-Length'))
    if (declaredLength > TEXT_LIMIT_BYTES) {
      await response.body?.cancel()
      throw new ApiError('文档超过 2 MiB 预览限制，请下载文档查看', 'DOCUMENT_TOO_LARGE')
    }
    if (!response.body) return ''
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8', { fatal: true })
    const parts: string[] = []
    let bytes = 0
    let complete = false
    try {
      while (true) {
        requestSignal.throwIfAborted()
        const { done, value } = await reader.read()
        requestSignal.throwIfAborted()
        if (done) { complete = true; break }
        bytes += value.byteLength
        if (bytes > TEXT_LIMIT_BYTES) {
          throw new ApiError('文档超过 2 MiB 预览限制，请下载文档查看', 'DOCUMENT_TOO_LARGE')
        }
        parts.push(decoder.decode(value, { stream: true }))
      }
      parts.push(decoder.decode())
      return parts.join('')
    } finally {
      try {
        if (!complete) await reader.cancel()
      } finally {
        // 已报错的流上 cancel() 也会拒绝，仍须释放 reader 所持的锁。
        reader.releaseLock()
      }
    }
  })
}

/** 下载复用认证与注销取消；signal 可绑定预览窗口或弹窗生命周期。 */
export async function downloadDocument(bankId: string, docId: string, name: string, signal?: AbortSignal): Promise<void> {
  const started = getSessionGeneration()
  const blob = await readDocument(bankId, docId, PDF_TIMEOUT_MS, signal, response => response.blob(), false)
  signal?.throwIfAborted()
  assertCurrentSession(started)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  try {
    link.href = url
    link.download = name
    document.body.appendChild(link)
    link.click()
  } finally {
    link.remove()
    URL.revokeObjectURL(url)
  }
}

/**
 * 必须从点击处理器直接调用：函数在第一次 await 前同步预开窗口。
 * 初次失败拒绝 Promise 供入口 toast 展示；窗口内可重试、下载，主动取消正常完成。
 */
export async function openPdfDocument(bankId: string, docId: string): Promise<void> {
  const preview = window.open('', '_blank')
  if (!preview) throw new ApiError('预览窗口被浏览器拦截，请允许弹出窗口后重试，或下载文档', 'DOCUMENT_POPUP_BLOCKED')
  preview.opener = null
  const page = preview.document
  page.title = 'PDF 文档预览'
  page.documentElement.lang = 'zh-CN'
  const style = page.createElement('style')
  style.textContent = `
    body{margin:0;font:16px/1.6 system-ui,sans-serif;color:#17243b;background:#f4f6fa}
    main{height:100vh;display:flex;flex-direction:column}header{padding:12px 20px;background:white}
    p{margin:0 0 8px;white-space:pre-wrap}button{font:inherit;min-height:44px;margin-right:12px;padding:6px 16px;cursor:pointer}
    button:focus-visible{outline:3px solid #2563eb;outline-offset:2px}button:disabled{cursor:wait}
    iframe{border:0;width:100%;flex:1;background:white} [role=alert]{color:#b91c1c}
  `
  page.head.appendChild(style)
  const main = page.createElement('main'), header = page.createElement('header')
  const status = page.createElement('p'), retry = page.createElement('button'), download = page.createElement('button')
  const frame = page.createElement('iframe')
  status.setAttribute('role', 'status')
  status.setAttribute('aria-live', 'polite')
  retry.type = download.type = 'button'
  retry.textContent = '重试预览'
  download.textContent = '下载文档'
  frame.title = 'PDF 文档内容'
  frame.hidden = true
  header.append(status, retry, download)
  main.append(header, frame)
  page.body.replaceChildren(main)

  return new Promise<void>((resolve, reject) => {
    const lifetime = new AbortController()
    let objectUrl: string | undefined
    let request: AbortController | undefined
    let disposed = false
    let settled = false
    const settle = (error?: unknown) => {
      if (settled) return
      settled = true
      if (error) reject(error)
      else resolve()
    }
    const revoke = () => {
      frame.removeAttribute('src')
      frame.hidden = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
      objectUrl = undefined
    }
    const dispose = (close = false) => {
      if (disposed) return
      disposed = true
      request?.abort()
      lifetime.abort()
      revoke()
      unsubscribe()
      window.clearInterval(watchClosed)
      preview.removeEventListener('pagehide', onWindowClosed)
      window.removeEventListener('pagehide', onParentClosed)
      retry.onclick = download.onclick = null
      if (close && !preview.closed) preview.close()
      settle()
    }
    const onWindowClosed = () => dispose()
    const onParentClosed = () => dispose(true)
    const unsubscribe = onSessionCleared(onParentClosed)
    const watchClosed = window.setInterval(() => { if (preview.closed) dispose() }, 250)
    preview.addEventListener('pagehide', onWindowClosed)
    window.addEventListener('pagehide', onParentClosed)
    const showError = (error: unknown) => {
      status.setAttribute('role', 'alert')
      status.textContent = error instanceof Error ? error.message : '打开失败，请重试或下载文档'
    }
    const run = async (asDownload = false) => {
      if (disposed || retry.disabled) return
      retry.disabled = download.disabled = true
      status.setAttribute('role', 'status')
      status.textContent = asDownload ? '正在下载文档…' : '正在载入 PDF 文档…'
      request = new AbortController()
      try {
        if (asDownload) {
          await downloadDocument(bankId, docId, `document-${docId}.pdf`, lifetime.signal)
          if (!disposed) status.textContent = '已开始下载文档'
        } else {
          revoke()
          const blob = await readDocument(bankId, docId, PDF_TIMEOUT_MS, request.signal, async response => {
            if (response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/pdf') {
              await response.body?.cancel()
              throw new ApiError('文档内容类型不是 PDF，请重试或下载文档', 'DOCUMENT_CONTENT_TYPE')
            }
            // PDF 只读取二进制 Blob，绝不进行文本解码。
            return new Blob([await response.blob()], { type: 'application/pdf' })
          })
          if (disposed || preview.closed) { dispose(); return }
          objectUrl = URL.createObjectURL(blob)
          frame.src = objectUrl
          frame.hidden = false
          status.textContent = 'PDF 已载入；如浏览器无法显示，可下载文档查看'
        }
        settle()
      } catch (error: unknown) {
        if (disposed || isDocumentPreviewCancelled(error)) { dispose(true); return }
        showError(error)
        settle(error)
      } finally {
        if (!disposed) retry.disabled = download.disabled = false
      }
    }
    retry.onclick = () => { void run() }
    download.onclick = () => { void run(true) }
    void run()
  })
}
