import { spawn } from 'node:child_process'
import console from 'node:console'
import process from 'node:process'
import { clearTimeout, setTimeout } from 'node:timers'
import { fileURLToPath, URL } from 'node:url'

const cwd = fileURLToPath(new URL('.', import.meta.url))
const scripts = [
  'latex',
  'auth-session', 'logout-session', 'isolation-session', 'document-upload',
  'document-preview', 'admin-panel', 'merge-frontend', 'ops-panel', 'e2e-auth',
]
const args = process.argv.slice(2)
if (args.some(arg => arg !== '--skip-build') || args.length > 1) {
  throw new Error('Usage: node run-regressions.mjs [--skip-build]')
}

async function run(label, args, timeout) {
  console.log(`\n=== ${label} ===`)
  const child = spawn(process.execPath, args, {
    cwd, stdio: 'inherit', detached: process.platform !== 'win32',
    env: { ...process.env, VITE_API_BASE_URL: '', VITE_WS_BASE_URL: '' },
  })
  let timedOut = false
  let interrupted = false
  let termination
  const stop = () => {
    if (termination) return
    termination = process.platform === 'win32'
      ? new Promise((resolve, reject) => {
        const killer = spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'inherit' })
        killer.once('error', reject)
        killer.once('close', code => code === 0 ? resolve() : reject(new Error(`taskkill exited ${code}`)))
      })
      : Promise.resolve().then(() => {
        try { process.kill(-child.pid, 'SIGKILL') } catch (error) {
          if (error.code !== 'ESRCH') throw error
        }
      })
    // Attach a rejection handler immediately; the result is checked after exit.
    termination.catch(error => console.error('Process cleanup failed:', error))
  }
  const interrupt = () => { interrupted = true; stop() }
  process.once('SIGINT', interrupt)
  process.once('SIGTERM', interrupt)
  const timer = setTimeout(() => { timedOut = true; stop() }, timeout)
  try {
    const code = await new Promise((resolve, reject) => {
      child.once('error', reject)
      child.once('close', (code, signal) => resolve(code ?? signal))
    })
    await termination
    if (timedOut) throw new Error(`${label} timed out after ${timeout / 1000}s`)
    if (interrupted) throw new Error(`${label} interrupted`)
    if (code !== 0) throw new Error(`${label} exited ${code}`)
  } finally {
    clearTimeout(timer)
    process.removeListener('SIGINT', interrupt)
    process.removeListener('SIGTERM', interrupt)
  }
}

try {
  if (!args.includes('--skip-build')) {
    await run('typecheck', ['node_modules/typescript/bin/tsc', '--noEmit'], 180_000)
    await run('build', ['node_modules/vite/bin/vite.js', 'build'], 180_000)
  }
  for (const name of scripts) {
    await run(name, [name === 'e2e-auth' ? 'e2e-auth.mjs' : `${name}-regression.mjs`],
      name === 'e2e-auth' ? 300_000 : 180_000)
  }
  console.log(`\nPASS: ${scripts.length} offline regression scripts`)
} catch (error) {
  console.error(error)
  process.exitCode = 1
}
