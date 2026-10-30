/** 设置与个人资料始终访问真实后端，不受出题演示适配器影响。 */
import { apiUrl } from './urls'

export { apiUrl } from './urls'

function describeDetail(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail.trim() || undefined
  if (Array.isArray(detail)) {
    return detail.map((item: unknown) => describeDetail(item)).filter(Boolean).join('；') || undefined
  }
  if (detail && typeof detail === 'object') {
    const value = detail as Record<string, unknown>
    const message = describeDetail(value.message ?? value.msg ?? value.error ?? value.detail)
    if (!message) return undefined
    // FastAPI 422 使用 loc/msg 数组；只显示字段位置和消息，不回显 input 等敏感字段。
    const location = Array.isArray(value.loc)
      ? value.loc.filter((part: unknown) => typeof part === 'string' || typeof part === 'number').join('.')
      : ''
    return location ? `${location}：${message}` : message
  }
  return undefined
}

export async function settingsRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(apiUrl(path), { ...init, headers })
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`
    try {
      const payload: unknown = await response.json()
      message = describeDetail(payload) ?? message
    } catch { /* 非 JSON 错误保留 HTTP 状态，不输出请求内容或凭据。 */ }
    throw new Error(message)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
