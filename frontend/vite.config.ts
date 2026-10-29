import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// base 用相对路径，保证 GitHub Pages 子路径部署可直接运行
export default defineConfig(({ mode }) => {
  const envDir = fileURLToPath(new URL('..', import.meta.url))
  const env = loadEnv(mode, envDir, ['FRONTEND_', 'BACKEND_', 'VITE_API_BASE_URL', 'VITE_WS_BASE_URL'])
  const value = (name: string, fallback = '') => env[name]?.trim() || fallback
  const port = (name: string, fallback: number) => {
    const configured = Number(value(name, String(fallback)))
    if (!Number.isInteger(configured) || configured < 1 || configured > 65535) {
      throw new Error(`${name} 必须是 1–65535 的整数端口`)
    }
    return configured
  }
  const backendHost = value('BACKEND_HOST', '127.0.0.1')
  const connectHost = backendHost === '0.0.0.0' ? '127.0.0.1'
    : backendHost === '::' || backendHost === '[::]' ? '[::1]'
    : backendHost.includes(':') && !backendHost.startsWith('[') ? `[${backendHost}]` : backendHost
  const backendTarget = `http://${connectHost}:${port('BACKEND_PORT', 8000)}`
  const apiBase = value('VITE_API_BASE_URL')
  const proxyTarget = value('FRONTEND_PROXY_TARGET')
    || (/^https?:\/\//i.test(apiBase) ? apiBase : backendTarget)
  const wsBase = value('VITE_WS_BASE_URL')
  const wsTarget = /^wss?:\/\//i.test(wsBase) || /^https?:\/\//i.test(wsBase) ? wsBase : proxyTarget
  const proxy = {
    '/api': { target: proxyTarget, ws: true },
    '/ws': { target: wsTarget, ws: true },
  }
  const host = value('FRONTEND_HOST', '127.0.0.1')

  return {
    base: './',
    envDir,
    // 共享 .env 中只有这两个公开地址需要进入浏览器构建产物。
    envPrefix: ['VITE_API_BASE_URL', 'VITE_WS_BASE_URL'],
    plugins: [react(), tailwindcss()],
    server: {
      host,
      port: port('FRONTEND_PORT', 5173),
      proxy,
    },
    preview: { host, port: port('FRONTEND_PREVIEW_PORT', 4173), proxy },
  }
})
