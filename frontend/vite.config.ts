import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// base 用相对路径，保证 GitHub Pages 子路径部署可直接运行
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '')
  const backendHost = env.BACKEND_HOST || '127.0.0.1'
  const backendPort = env.BACKEND_PORT || '8000'

  return {
    base: './',
    envDir: '..',
    plugins: [react(), tailwindcss()],
    server: {
      host: env.FRONTEND_HOST || '127.0.0.1',
      port: Number(env.FRONTEND_PORT || '5173'),
      proxy: {
        // 前端所有 /api 请求转发到根目录 .env 配置的出题后端
        '/api': env.VITE_API_BASE_URL || `http://${backendHost}:${backendPort}`,
      },
    },
  }
})
