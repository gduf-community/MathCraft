import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// base 用相对路径，保证 GitHub Pages 子路径部署可直接运行
export default defineConfig({
  base: './',
  envDir: false,
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    proxy: {
      // 前端所有 /api 请求转发到本地后端（用 127.0.0.1 避免 localhost 解析为 IPv6 连不上）
      '/api': 'http://127.0.0.1:8000',
      // 头像等媒体文件
      '/media': 'http://127.0.0.1:8000',
    },
  },
})
