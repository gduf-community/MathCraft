/* global URL, Response, Headers, console, Blob, process */
/** 多标签、重新加载及下载边界；只使用假网络和内存浏览器替身。 */
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { resolveConfig } from 'vite'
const require = createRequire(new URL('./package.json', import.meta.url))
const ts = require('typescript')
const source = await readFile(new URL('./src/api/session.ts', import.meta.url), 'utf8')
const stores = []
globalThis.testStores = stores
const messages = []
const channels = []
globalThis.BroadcastChannel = class {
  constructor() { channels.push(this) }
  addEventListener(_event, listener) { this.listener = listener }
  postMessage(message) {
    messages.push(message)
    for (const channel of channels) if (channel !== this) channel.listener?.({ data: message })
  }
}
let tail = Promise.resolve()
let lockRequests = 0
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { locks: {
  request: (name, action) => {
    assert.equal(name, 'mathcraft-refresh')
    lockRequests += 1
    const next = tail.then(action)
    tail = next.catch(() => {})
    return next
  },
} } })
const compile = code => 'data:text/javascript;base64,' + Buffer.from(ts.transpileModule(code, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText).toString('base64')
async function tab(storage = new Map()) {
  const index = stores.length
  stores.push({ getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) })
  const url = compile(source.replace("import { apiUrl } from './urls'", 'const apiUrl = path => path')
    .replaceAll('sessionStorage', `globalThis.testStores[${index}]`))
  return { session: await import(url), storage, url }
}
const result = (id, sid = id + '-session', role = 'student') => ({
  access_token: 'fake.' + Buffer.from(JSON.stringify({ sub: id, sid })).toString('base64url') + '.fake',
  token_type: 'bearer', expires_in: 900,
  user: { id, account: id, role, identity: role === 'admin' ? '管理员' : role === 'teacher' ? '教师' : '学生', display_name: id, email: id + '@example.invalid', email_verified: true },
})
const login = (target, value) => target.session.establishSession(async () => value, response => response.user)
const config = { site_key: 'fake', csrf_token: 'fake-csrf', admin_contact: 'fake administrator', methods: ['account_password', 'email_code'] }
globalThis.fetch = async path => {
  if (path.endsWith('/config')) return Response.json(config)
  assert.equal(path, '/api/auth/logout')
  return new Response(null, { status: 204 })
}
const a = await tab(), sibling = await tab(), otherSession = await tab(), b = await tab()
await login(a, result('A'))
await login(sibling, result('A'))
await login(otherSession, result('A', 'another-A-session'))
await login(b, result('B'))
await a.session.logoutSession()
assert.equal(a.session.getApiToken(), '')
assert.equal(sibling.session.getApiToken(), '', '同 sid 标签立即清除')
assert.ok(otherSession.session.getApiToken(), '同用户其他 sid 保留')
assert.ok(b.session.getApiToken(), '不同用户保留')
assert.deepEqual(messages.at(-1), { type: 'invalidate', scope: 'session', userId: 'A', sid: 'A-session' })
await login(a, result('A'))
await login(sibling, result('A'))
a.session.invalidateUserSessions()
assert.equal(sibling.session.getApiToken(), '')
assert.equal(otherSession.session.getApiToken(), '', '安全操作通知同用户所有 sid')
assert.ok(b.session.getApiToken())
await login(a, result('A'))
await login(otherSession, result('A', 'another-A-session'))
const anonymous = await tab()
anonymous.session.invalidateUserSessions('A@example.invalid')
assert.equal(a.session.getApiToken(), '')
assert.equal(otherSession.session.getApiToken(), '')
assert.ok(b.session.getApiToken(), '重置其他邮箱不影响 B')
channels.at(-1).postMessage({ type: 'invalidate' })
assert.ok(b.session.getApiToken(), '忽略旧版无范围消息')
console.log('PASS: session/user/email scoped invalidation without credentials')

// 模块重载模拟刷新页面；共享 Cookie 为 B 时不得恢复 A 标签成 B。
await login(a, result('A'))
let refreshes = 0
globalThis.fetch = async path => {
  if (path.endsWith('/config')) return Response.json(config)
  assert.equal(path, '/api/auth/refresh')
  refreshes += 1
  return Response.json(result('B'))
}
const reloadedA = await tab(a.storage)
await assert.rejects(reloadedA.session.refreshSession(), error => error.code === 'SESSION_IDENTITY_CHANGED')
assert.equal(reloadedA.session.getApiToken(), '')
assert.ok(b.session.getApiToken())
const reloadedB = await tab(b.storage)
await reloadedB.session.refreshSession()
assert.equal(reloadedB.session.getApiToken(), result('B').access_token)
assert.equal(refreshes, 2)
console.log('PASS: reload preserves expected account; shared cookie cannot switch identity')

// 失败退出标记跨重载保留，访问令牌不得持久化；显式登录才能解除阻断。
const exiting = await tab()
await login(exiting, result('C'))
globalThis.fetch = async path => {
  if (path.endsWith('/config')) return Response.json(config)
  throw new TypeError('synthetic network failure')
}
await assert.rejects(exiting.session.logoutSession())
const afterFailure = await tab(exiting.storage)
let networkCalls = 0
globalThis.fetch = async () => { networkCalls += 1; throw new Error('unexpected network') }
await assert.rejects(afterFailure.session.refreshSession(), error => error.code === 'SESSION_ENDED')
assert.equal(networkCalls, 0)
assert.ok(!JSON.stringify([...exiting.storage.values()]).includes(result('C').access_token))
await assert.rejects(afterFailure.session.establishSession(async () => { throw new Error('fake login failure') }, value => value))
await assert.rejects(afterFailure.session.refreshSession(), error => error.code === 'SESSION_ENDED')
await login(afterFailure, result('D'))
assert.equal(afterFailure.session.getApiToken(), result('D').access_token)
console.log('PASS: failed logout blocks restore after reload until explicit successful login')

// 使用真实下载函数，延迟 blob 完成至 B 登录后，不得触发浏览器保存。
const downloading = await tab()
await login(downloading, result('A'))
const backendSource = (await readFile(new URL('./src/api/backend.ts', import.meta.url), 'utf8'))
  .replace("import { apiUrl } from './urls'", 'const apiUrl = path => path')
  .replaceAll("from './session'", `from '${downloading.url}'`)
const backendUrl = compile(backendSource)
const backend = await import(backendUrl)
let finishBlob, beginBlob
const body = new Promise(resolve => { finishBlob = resolve })
const entered = new Promise(resolve => { beginBlob = resolve })
globalThis.fetch = async () => ({ ok: true, status: 200, blob: () => { beginBlob(); return body } })
let clicks = 0
globalThis.document = { createElement: () => ({ click: () => { clicks += 1 }, remove() {} }), body: { appendChild() {} } }
const download = backend.downloadDocument('fake-bank', 'fake-doc', 'fake.txt')
const rejectedDownload = assert.rejects(download, error => error.code === 'SESSION_ENDED')
await entered
await login(downloading, result('B'))
finishBlob(new Blob(['synthetic document']))
await rejectedDownload
assert.equal(clicks, 0)
globalThis.fetch = async () => new Response('synthetic document')
await backend.downloadDocument('fake-bank', 'fake-doc', 'fake.txt')
assert.equal(clicks, 1)
console.log('PASS: delayed download body rejected across identity change; current download works')

// 两个登录入口均由响应识别三角色，不发送 role；账号入口允许有无邮箱。
const authSource = (await readFile(new URL('./src/api/auth.ts', import.meta.url), 'utf8'))
  .replaceAll("from './session'", `from '${downloading.url}'`)
  .replaceAll("from './backend'", `from '${backendUrl}'`)
const auth = await import(compile(authSource))
for (const role of ['student', 'teacher', 'admin']) {
  for (const verified of [false, true]) {
    const value = result(role, role + '-session', role)
    value.user.email = verified ? role + '@example.invalid' : null
    value.user.email_verified = verified
    globalThis.fetch = async (path, init) => {
      assert.equal(path, '/api/auth/login/account')
      assert.equal(init.method, 'POST')
      assert.deepEqual(JSON.parse(init.body), { account: 'fake-account', password: 'fake-password', turnstile_token: 'fake-challenge' })
      assert.equal(new Headers(init.headers).has('Authorization'), false)
      return Response.json(value)
    }
    const mapped = await auth.loginAccount('fake-account', 'fake-password', 'fake-challenge')
    assert.equal(mapped.role, role)
    assert.equal(mapped.emailVerified, verified)
  }
  globalThis.fetch = async (path, init) => {
    assert.equal(path, '/api/auth/login/email')
    assert.deepEqual(JSON.parse(init.body), { email: role + '@example.invalid', challenge_id: 'fake-login', code: '123456' })
    assert.equal(new Headers(init.headers).has('Authorization'), false)
    return Response.json(result(role, role + '-session', role))
  }
  assert.equal((await auth.loginEmail({ email: role + '@example.invalid', challenge_id: 'fake-login', code: '123456' })).role, role)
}
assert.equal(backend.mapAuthUser(downloading.session.parseApiUser(result('A').user), '').passwordChangeRecommended, false)
assert.equal(backend.mapAuthUser(downloading.session.parseApiUser({ ...result('A').user, password_change_recommended: true }), '').passwordChangeRecommended, true)
assert.throws(() => downloading.session.parseApiUser({ ...result('A').user, password_change_recommended: 'true' }), error => error.code === 'INVALID_AUTH_RESPONSE')
assert.equal('register' in auth, false)
assert.equal('loginPassword' in auth, false)
globalThis.fetch = async path => { assert.equal(path, '/api/auth/config'); return Response.json(config) }
assert.deepEqual((await auth.getAuthConfig()).methods, config.methods)
assert.equal((await auth.getAuthConfig()).admin_contact, config.admin_contact)
console.log('PASS: account/email login supports three roles, optional email, verified flag, no role or removed exports')

// 首次绑定/换绑发码必须带 Bearer；公开登录和恢复发码不得借用本标签身份。
await login(downloading, result('A'))
for (const purpose of ['login', 'reset_password', 'email_bind', 'email_change_old', 'email_change_new']) {
  const payload = { email: 'A@example.invalid', purpose, turnstile_token: 'fake-challenge',
    ...(purpose.startsWith('email_change') ? { change_id: 'fake-change' } : {}) }
  globalThis.fetch = async (path, init) => {
    assert.equal(path, '/api/auth/email-code')
    assert.equal(init.method, 'POST')
    assert.deepEqual(JSON.parse(init.body), payload)
    assert.equal(new Headers(init.headers).get('Authorization'),
      purpose === 'email_bind' || purpose.startsWith('email_change') ? 'Bearer ' + result('A').access_token : null)
    return Response.json({ challenge_id: 'fake-code', expires_in: 300, retry_after: 60 }, { status: 202 })
  }
  assert.equal((await auth.sendEmailCode(payload)).challenge_id, 'fake-code')
}
console.log('PASS: binding/change code authenticated; login/reset code anonymous')

// 所有真实安全操作必须持锁到 Cookie 删除响应到达；B 登录只能随后写入 Cookie。
const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
const securityCases = [
  { path: '/api/auth/password', method: 'PUT', authenticated: true,
    payload: { old_password: 'fake-old', new_password: 'fake-new', confirm_password: 'fake-new' },
    invoke: api => api.changePasswordCurrent('fake-old', 'fake-new', 'fake-new') },
  { path: '/api/auth/password/reset', method: 'POST', authenticated: false,
    payload: { email: 'A@example.invalid', challenge_id: 'fake', code: '123456', new_password: 'fake-new', confirm_password: 'fake-new' },
    invoke: api => api.resetPassword({ email: 'A@example.invalid', challenge_id: 'fake', code: '123456', new_password: 'fake-new', confirm_password: 'fake-new' }) },
  { path: '/api/users/me/email', method: 'PUT', authenticated: true,
    payload: { change_id: 'fake', old_challenge_id: 'fake-old', old_code: '123456', new_challenge_id: 'fake-new', new_code: '654321' },
    invoke: api => api.changeEmail({ change_id: 'fake', old_challenge_id: 'fake-old', old_code: '123456', new_challenge_id: 'fake-new', new_code: '654321' }) },
  { path: '/api/users/me/email-binding', method: 'PUT', authenticated: true,
    payload: { email: 'bound@example.invalid', current_password: 'fake-old', challenge_id: 'fake-bind', code: '123456' },
    invoke: api => api.bindEmail({ email: 'bound@example.invalid', current_password: 'fake-old', challenge_id: 'fake-bind', code: '123456' }) },
  { path: '/api/users/me/email', method: 'DELETE', authenticated: true,
    payload: { current_password: 'fake-old' }, invoke: api => api.unbindEmail('fake-old') },
]
for (const scenario of securityCases) {
  await login(downloading, result('A'))
  const nextTab = await tab()
  const nextAuth = await import(compile((await readFile(new URL('./src/api/auth.ts', import.meta.url), 'utf8'))
    .replaceAll("from './session'", `from '${nextTab.url}'`)
    .replaceAll("from './backend'", `from '${backendUrl}'`)))
  const enteredMutation = deferred(), releaseMutation = deferred()
  let sharedCookie = 'A', loginCalls = 0
  const events = []
  globalThis.fetch = async (path, init) => {
    if (path === scenario.path) {
      assert.equal(init.method, scenario.method)
      assert.deepEqual(JSON.parse(init.body), scenario.payload)
      assert.equal(init.credentials, 'include')
      assert.equal(new Headers(init.headers).get('Authorization'), scenario.authenticated ? 'Bearer ' + result('A').access_token : null)
      assert.equal(sharedCookie, 'A')
      events.push('mutation request')
      enteredMutation.resolve()
      await releaseMutation.promise
      sharedCookie = '' // 模拟浏览器应用延迟响应的删除 Cookie。
      events.push('mutation response')
      return new Response(null, { status: 204 })
    }
    assert.equal(path, '/api/auth/login/account')
    loginCalls += 1
    sharedCookie = 'B'
    events.push('login response')
    return Response.json(result('B'))
  }
  const mutation = scenario.invoke(auth)
  await enteredMutation.promise
  const locksBefore = lockRequests
  const nextLogin = nextAuth.loginAccount('fake-B', 'fake-password', 'fake-challenge')
  assert.equal(lockRequests, locksBefore + 1, 'B 登录已排入同一把锁')
  for (let turn = 0; turn < 8; turn += 1) await Promise.resolve()
  assert.equal(loginCalls, 0, '旧删除响应到达前不允许发送新登录')
  releaseMutation.resolve()
  await Promise.all([mutation, nextLogin])
  assert.equal(downloading.session.getApiToken(), '', '安全操作成功必须清除本标签会话')
  assert.equal(sharedCookie, 'B')
  assert.equal(nextTab.session.getApiToken(), result('B').access_token)
  assert.deepEqual(events, ['mutation request', 'mutation response', 'login response'])
}
console.log('PASS: password/reset/email change/bind/unbind payloads and delayed cookie deletion serialize before other-tab login')

// 安全操作失败保留当前会话及其他标签，不广播成功撤销。
for (const scenario of securityCases.filter(value => value.authenticated)) {
  await login(downloading, result('A'))
  const before = messages.length
  globalThis.fetch = async (path, init) => {
    assert.equal(path, scenario.path)
    assert.equal(init.method, scenario.method)
    return Response.json({ detail: { code: 'PASSWORD_INVALID', message: 'fake invalid proof' } }, { status: 400 })
  }
  await assert.rejects(scenario.invoke(auth), error => error.code === 'PASSWORD_INVALID')
  assert.equal(downloading.session.getApiToken(), result('A').access_token)
  assert.equal(messages.length, before)
}
console.log('PASS: failed security mutation preserves session and emits no invalidation')

// 过期预检在锁外刷新；锁内遇到过期 401 不再申请同一把锁或重放写请求。
for (const scenario of securityCases.filter(value => value.authenticated)) {
  await login(downloading, result('A'))
  downloading.session.setApiToken(result('A').access_token, -1)
  const calls = []
  globalThis.fetch = async path => {
    calls.push(path)
    if (path.endsWith('/config')) return Response.json(config)
    if (path.endsWith('/refresh')) return Response.json(result('A'))
    assert.equal(path, scenario.path)
    return new Response(null, { status: 204 })
  }
  await scenario.invoke(auth)
  assert.deepEqual(calls, ['/api/auth/config', '/api/auth/refresh', scenario.path])
  await login(downloading, result('A'))
  calls.length = 0
  globalThis.fetch = async path => {
    calls.push(path)
    assert.equal(path, scenario.path)
    return Response.json({ detail: { code: 'ACCESS_TOKEN_EXPIRED' } }, { status: 401 })
  }
  await assert.rejects(scenario.invoke(auth), error => error.code === 'ACCESS_TOKEN_EXPIRED')
  assert.deepEqual(calls, [scenario.path])
}
console.log('PASS: cookie mutations refresh before locking; expired rejection inside lock never refreshes or replays')

// 排队等待期间本标签切换身份，旧安全写操作必须在发送 HTTP 前被拒绝。
for (const scenario of securityCases) {
  await login(downloading, result('A'))
  const held = deferred(), release = deferred()
  const blocker = globalThis.navigator.locks.request('mathcraft-refresh', async () => { held.resolve(); await release.promise })
  await held.promise
  let writes = 0
  globalThis.fetch = async () => { writes += 1; throw new Error('unexpected stale write') }
  const mutation = scenario.invoke(auth)
  const rejection = assert.rejects(mutation, error => error.code === 'SESSION_ENDED')
  for (let turn = 0; turn < 8; turn += 1) await Promise.resolve()
  const nextLogin = login(downloading, result('B'))
  release.resolve()
  await Promise.all([blocker, rejection, nextLogin])
  assert.equal(writes, 0)
  assert.equal(downloading.session.getApiToken(), result('B').access_token)
}
console.log('PASS: queued cookie mutations reject obsolete generations before sending HTTP')

// 实际 AuthProvider 的意图保护，Hook 替身只记录状态与运行 effect。
const providerSource = (await readFile(new URL('./src/store/AuthContext.tsx', import.meta.url), 'utf8'))
  .replace("import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'", 'const { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } = globalThis.testHooks')
  .replace("import { fetchAuthUser, logout as authLogout } from '../api/auth'", 'const { fetchAuthUser, authLogout } = globalThis.testAuth')
  .replace("import { ApiError, onSessionCleared, refreshSession } from '../api/session'", 'const { ApiError, onSessionCleared, refreshSession } = globalThis.testAuth')
  .replace('return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>', 'void children; return value')
for (const fail of [false, true]) {
  let cursor = 0
  const slots = [], effects = []
  globalThis.testHooks = {
    createContext: value => ({ value }),
    useContext: context => context.value,
    useCallback: fn => fn,
    useMemo: fn => fn(),
    useRef: value => { const index = cursor++; return slots[index] ??= { current: value } },
    useState: initial => {
      const index = cursor++
      if (!(index in slots)) slots[index] = initial
      return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value }]
    },
    useEffect: (effect, dependencies) => {
      const index = cursor++
      if (!slots[index] || dependencies.some((value, i) => slots[index][i] !== value)) effects.push(effect)
      slots[index] = dependencies
    },
  }
  let finishRestore, failRestore, enteredRestore
  const pendingRestore = new Promise((resolve, reject) => { finishRestore = resolve; failRestore = reject })
  const enteredRestorePromise = new Promise(resolve => { enteredRestore = resolve })
  globalThis.testAuth = {
    ApiError: downloading.session.ApiError,
    fetchAuthUser: () => { enteredRestore(); return pendingRestore },
    authLogout: async () => {},
    onSessionCleared: () => () => {},
    refreshSession: async () => {},
  }
  globalThis.localStorage = { removeItem() {} }
  const { AuthProvider } = await import(compile(providerSource + `\n// case ${fail}`))
  const render = () => { cursor = 0; return AuthProvider({ children: null }) }
  const provider = render()
  for (const effect of effects.splice(0)) effect()
  await enteredRestorePromise
  provider.signIn({ userId: 'B', role: 'student', username: 'B', emailVerified: false })
  if (fail) failRestore(new Error('synthetic restore failure'))
  else finishRestore({ userId: 'A', role: 'student', username: 'A', emailVerified: false })
  for (let turn = 0; turn < 8; turn += 1) await Promise.resolve()
  const settled = render()
  assert.equal(settled.user.userId, 'B')
  assert.equal(settled.restoreError, '')
  assert.equal(settled.restoring, false)
}
console.log('PASS: AuthProvider ignores old restoration success and failure after explicit sign-in')

// 只创建和读取本测试的假环境文件，绝不读取工作树个人环境文件。
const fixture = await mkdtemp(join(tmpdir(), 'mathcraft-env-regression-'))
try {
  await writeFile(join(fixture, '.env'), 'VITE_API_BASE_URL=https://fake.invalid\n')
  for (const name of ['vite.config.ts', 'vite.auth-test.config.mjs']) {
    const resolved = await resolveConfig({ root: fixture, configFile: fileURLToPath(new URL(name, import.meta.url)), logLevel: 'silent' }, 'build')
    assert.notEqual(resolved.envDir, fixture)
    assert.equal(resolved.env.VITE_API_BASE_URL, process.env.VITE_API_BASE_URL)
  }
} finally { await rm(fixture, { recursive: true, force: true }) }
console.log('PASS: both Vite configurations ignore synthetic root environment file')
