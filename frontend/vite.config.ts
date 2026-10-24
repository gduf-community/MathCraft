import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// base 用相对路径，保证 GitHub Pages 子路径部署可直接运行
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // 前端所有 /api 请求转发到本地后端
      '/api': 'http://localhost:8000',
    },
  },
})
