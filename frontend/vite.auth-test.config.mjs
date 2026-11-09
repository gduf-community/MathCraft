import { mkdtempSync, rmdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import process from 'node:process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
// Vite 5 的 envDir:false 会回退到根目录；每次启动使用独立空目录。
const envDir = mkdtempSync(join(tmpdir(), 'mathcraft-vite-env-'))
process.once('exit', () => rmdirSync(envDir))
export default defineConfig({ envDir, plugins: [react(), tailwindcss()], server: { host: '127.0.0.1', port: 5178, strictPort: true } })
