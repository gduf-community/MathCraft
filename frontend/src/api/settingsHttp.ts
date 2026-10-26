/** 设置与个人资料始终访问真实后端，不受出题演示适配器影响。 */
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`
}

function describeDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item: unknown) => describeDetail(item)).join('；')
  if (detail && typeof detail === 'object') {
    const value = detail as Record<string, unknown>
    const message = value.message ?? value.msg ?? value.error
    if (typeof message === 'string') return message
  }
  return '请求失败，请检查配置后重试'
}

export async function settingsRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(apiUrl(path), { ...init, headers })
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`
    try {
      const payload: unknown = await response.json()
      if (payload && typeof payload === 'object' && 'detail' in payload) message = describeDetail(payload.detail)
    } catch { /* 非 JSON 错误保留 HTTP 状态，不输出请求内容或凭据。 */ }
    throw new Error(message)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
