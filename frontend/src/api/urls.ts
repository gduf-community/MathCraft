/** 公开地址来自 Vite 开发／构建进程的环境变量（项目 .env 已隔离）；API 地址留空时使用同源路径。 */
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '')
const WS_BASE = (import.meta.env.VITE_WS_BASE_URL ?? '').trim().replace(/\/+$/, '')

export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

/** path 包含完整路由（例如 /ws/knowledge-bases/{name}/progress）。 */
export function wsUrl(path: string): string {
  const base = WS_BASE || API_BASE
  const url = new URL(`${base}${path.startsWith('/') ? path : `/${path}`}`, window.location.origin)
  url.protocol = url.protocol === 'https:' || url.protocol === 'wss:' ? 'wss:' : 'ws:'
  return url.href
}
