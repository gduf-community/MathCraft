/* global process, console, URL, Response */
/** HTTP 会话边界回归：使用真实会话模块，仅替换浏览器和网络。 */
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
const require = createRequire(process.env.AUTH_TYPESCRIPT_PACKAGE ?? new URL('./package.json', import.meta.url))
const ts = require('typescript')
let tail = Promise.resolve()
Object.defineProperty(globalThis, 'navigator', { value: { locks: { request: (_name, action) => {
  const next = tail.then(action); tail = next.catch(() => {}); return next
} } }, configurable: true })
class TestChannel {
  static listener
  addEventListener(_name, listener) { TestChannel.listener = listener }
  postMessage() {}
}
globalThis.BroadcastChannel = TestChannel
const source = (await readFile(new URL('./src/api/session.ts', import.meta.url), 'utf8')).replace("import { apiUrl } from './urls'", 'const apiUrl = path => path')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText
const session = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'))
const user = (id, role = 'student') => ({ id, account: id, role, identity: role === 'teacher' ? '教师' : '学生', display_name: id })
const result = (id, role) => ({ access_token: 'token-' + id, token_type: 'bearer', expires_in: 900, user: user(id, role) })
const config = { site_key: 'test-key', csrf_token: 'test-csrf', available: true }
const response = body => Response.json(body)
const login = body => session.establishSession(async () => body, value => value.user)
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
for (const bad of [ { ...result('A'), user: undefined }, { ...result('A'), expires_in: 'invalid' }, { ...result('A'), expires_in: Infinity }, { ...result('A'), expires_in: 0 }, result('A', 'admin') ]) {
  await assert.rejects(login(bad))
  assert.equal(session.getApiToken(), '')
}
await assert.rejects(session.establishSession(async () => result('A'), () => { throw new Error('mapping failure') }))
assert.equal(session.getApiToken(), '')
await login(result('A'))
let businessCalls = 0, cleared = 0
session.onSessionCleared(() => { cleared += 1 })
globalThis.fetch = async path => {
  if (path.endsWith('/config')) return response(config)
  if (path.endsWith('/refresh')) return response(result('B', 'teacher'))
  businessCalls += 1
  return Response.json({ detail: { code: 'ACCESS_TOKEN_EXPIRED' } }, { status: 401 })
}
await assert.rejects(session.request('/api/write', { method: 'POST', body: '{}' }), error => error.code === 'SESSION_IDENTITY_CHANGED')
assert.equal(businessCalls, 1)
assert.equal(session.getApiToken(), '')
assert.equal(cleared, 1)
for (const success of [true, false]) {
  await login(result('A'))
  const entered = deferred(), pending = deferred()
  globalThis.fetch = async path => {
    if (path.endsWith('/config')) return response(config)
    entered.resolve(); return pending.promise
  }
  const old = session.refreshSession(); const rejected = assert.rejects(old)
  await entered.promise
  TestChannel.listener({ data: { type: 'invalidate' } })
  const newLogin = login(result('C'))
  pending.resolve(success ? response(result('A')) : Response.json({}, { status: 401 }))
  await Promise.all([rejected, newLogin])
  assert.equal(session.getApiToken(), 'token-C')
}
// 刷新响应也必须完整校验，不能残留已失效的旧凭据。
for (const bad of [{ ...result('A'), expires_in: 'invalid' }, { ...result('A'), user: undefined }]) {
  await login(result('A'))
  globalThis.fetch = async path => response(path.endsWith('/config') ? config : bad)
  await assert.rejects(session.refreshSession(), error => error.code === 'INVALID_AUTH_RESPONSE')
  assert.equal(session.getApiToken(), '')
}
// 旧业务401延迟到新登录之后：不能清理新账号，也不能以新账号重放旧写入。
await login(result('A'))
const oldWrite = deferred(), writing = deferred()
let sent = 0
globalThis.fetch = async () => { sent += 1; writing.resolve(); return oldWrite.promise }
const write = session.request('/api/write', { method: 'POST', body: '{}' })
const rejectedWrite = assert.rejects(write, error => error.code === 'SESSION_ENDED')
await writing.promise
await login(result('C'))
oldWrite.resolve(Response.json({ detail: { code: 'ACCESS_TOKEN_EXPIRED' } }, { status: 401 }))
await rejectedWrite
assert.equal(sent, 1)
assert.equal(session.getApiToken(), 'token-C')
// 同身份refresh保留会话；已撤销的业务请求不得触发刷新或重放。
await login(result('A'))
let refreshCalls = 0, writes = 0
globalThis.fetch = async path => {
  if (path.endsWith('/config')) return response(config)
  if (path.endsWith('/refresh')) { refreshCalls += 1; return response(result('A')) }
  writes += 1
  return Response.json({ detail: { code: writes === 1 ? 'ACCESS_TOKEN_EXPIRED' : 'SESSION_REVOKED' } }, { status: writes < 3 ? 401 : 200 })
}
await assert.rejects(session.request('/api/write', { method: 'POST', body: '{}' }))
assert.equal(refreshCalls, 1)
assert.equal(writes, 2)
await login(result('A'))
globalThis.fetch = async () => response({ ...config, csrf_token: 42 })
await assert.rejects(session.getAuthConfig())
console.log('PASS: malformed auth/config, atomic install, identity switch no replay, stale refresh success/failure')
