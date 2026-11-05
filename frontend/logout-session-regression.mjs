/* global Response, Headers, URL, console */
/** 真实会话模块的注销边界：共享 Cookie 不得代替本标签 Bearer。 */
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
const require = createRequire(new URL('./package.json', import.meta.url))
const ts = require('typescript')
let tail = Promise.resolve()
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { locks: {
  request: (_name, action) => {
    const next = tail.then(action)
    tail = next.catch(() => {})
    return next
  },
} } })
const broadcasts = []
globalThis.BroadcastChannel = class {
  addEventListener() {}
  postMessage(value) { broadcasts.push(value) }
}
const source = (await readFile(new URL('./src/api/session.ts', import.meta.url), 'utf8'))
  .replace("import { apiUrl } from './urls'", 'const apiUrl = path => path')
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020,
} }).outputText
const session = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'))
const result = id => ({ access_token: 'token-' + id, token_type: 'bearer', expires_in: 900,
  user: { id, account: id, role: 'student', identity: '学生', display_name: id } })
const login = id => session.establishSession(async () => result(id), value => value.user)
const calls = []
globalThis.fetch = async (path, init = {}) => {
  calls.push([path, init])
  if (path === '/api/auth/config') return Response.json({ site_key: 'test', csrf_token: 'fake-csrf' })
  assert.equal(path, '/api/auth/logout', '注销不应刷新共享 Cookie 的账号')
  assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer token-A')
  assert.equal(new Headers(init.headers).get('X-CSRF-Token'), 'fake-csrf')
  assert.equal(init.credentials, 'include')
  return new Response(null, { status: 204 })
}
await login('A')
session.setApiToken('token-A', -1)
await session.logoutSession()
assert.equal(session.getApiToken(), '')
assert.equal(calls.length, 2)
assert.equal(broadcasts.length, 0, '单设备注销不得无条件清空其他标签的不同账号')
calls.length = 0
await session.logoutSession()
assert.equal(calls.length, 0, '没有本标签凭据时不得匿名注销其他账号')
await login('A')
let entered, finish
const pending = new Promise(resolve => { finish = resolve })
const started = new Promise(resolve => { entered = resolve })
globalThis.fetch = async path => {
  if (path === '/api/auth/config') return Response.json({ site_key: 'test', csrf_token: 'fake-csrf' })
  entered()
  return pending
}
const logout = session.logoutSession()
await started
const newLogin = login('B')
finish(new Response(null, { status: 204 }))
await Promise.all([logout, newLogin])
assert.equal(session.getApiToken(), 'token-B', '旧注销完成不能清除新登录')
console.log('PASS: logout binds original bearer, no refresh/broadcast, preserves newer login')

for (const failConfig of [false, true]) {
  await login('A')
  let fail = true, revocations = 0
  globalThis.fetch = async (path, init = {}) => {
    if (path === '/api/auth/config') {
      if (fail && failConfig) throw new TypeError('fake configuration network failure')
      return Response.json({ site_key: 'test', csrf_token: 'fake-csrf' })
    }
    assert.equal(path, '/api/auth/logout')
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer token-A')
    revocations += 1
    return fail ? Response.json({ detail: { code: 'UNAVAILABLE', message: 'fake outage' } }, { status: 503 })
      : new Response(null, { status: 204 })
  }
  await assert.rejects(session.logoutSession())
  assert.equal(session.getApiToken(), '', '注销失败仍不可继续业务请求')
  await assert.rejects(session.refreshSession(), error => error.code === 'SESSION_ENDED')
  fail = false
  await session.logoutSession()
  assert.equal(revocations, failConfig ? 1 : 2, '重试必须发送原会话撤销，不能假成功')
  await session.logoutSession()
  assert.equal(revocations, failConfig ? 1 : 2, '确认撤销后不得继续保留凭据')
}
console.log('PASS: failed config/logout preserves revoke-only credential until confirmed retry')

for (const mode of ['network', 'malformed', 'mapping']) {
  await login('A')
  let outage = true, revocations = 0
  globalThis.fetch = async (path, init = {}) => {
    if (path === '/api/auth/config') return Response.json({ site_key: 'test', csrf_token: 'fake-csrf' })
    assert.equal(path, '/api/auth/logout')
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer token-A')
    revocations += 1
    return outage ? Response.json({ detail: { code: 'UNAVAILABLE' } }, { status: 503 })
      : new Response(null, { status: 204 })
  }
  await assert.rejects(session.logoutSession())
  await assert.rejects(session.establishSession(async () => {
    if (mode === 'network') throw new TypeError('fake login network failure')
    return mode === 'malformed' ? {} : result('B')
  }, () => { throw new Error('fake login mapping failure') }))
  assert.equal(session.getApiToken(), '', '失败登录不得恢复业务认证')
  await assert.rejects(session.refreshSession(), error => error.code === 'SESSION_ENDED')
  outage = false
  await session.logoutSession()
  assert.equal(revocations, 2, `${mode}: 登录失败后仍须真实撤销原会话`)
  await session.logoutSession()
  assert.equal(revocations, 2, '确认后再次退出不重发')
}
console.log('PASS: failed network/parse/mapping login preserves original logout retry')
