/* global process, console, URL, Response, FormData, Blob, Headers */
/** HTTP 与 XHR 上传会话边界回归：使用真实模块，仅替换浏览器和网络。 */
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
const require = createRequire(process.env.AUTH_TYPESCRIPT_PACKAGE ?? new URL('./package.json', import.meta.url))
const ts = require('typescript')
const tabStorage = new Map()
globalThis.sessionStorage = {
  getItem: key => tabStorage.get(key) ?? null,
  setItem: (key, value) => tabStorage.set(key, value),
}

let tail = Promise.resolve()
let controlledLocks = false
const scheduledLocks = []
// 对抗性调度器：只在代次回归中手动启动回调，刻意允许重叠，
// 不把真实 Web Lock 的串行保证当作 catch/finally 归属正确的证据。
function runScheduledLock() {
  const run = scheduledLocks.shift()
  assert.ok(run, '应存在待启动的锁回调')
  run()
}
Object.defineProperty(globalThis, 'navigator', { value: { locks: { request: (_name, action) => {
  if (controlledLocks) return new Promise((resolve, reject) => {
    scheduledLocks.push(() => { Promise.resolve().then(action).then(resolve, reject) })
  })
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
const sessionModuleUrl = 'data:text/javascript;base64,' + Buffer.from(compiled).toString('base64')
const session = await import(sessionModuleUrl)
const backendSource = (await readFile(new URL('./src/api/backend.ts', import.meta.url), 'utf8'))
  .replace("import { apiUrl } from './urls'", 'const apiUrl = path => path')
  .replaceAll("from './session'", `from '${sessionModuleUrl}'`)
const backendCompiled = ts.transpileModule(backendSource, { compilerOptions: {
  module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020,
} }).outputText
const { uploadDocument, createBankWithDocument } = await import('data:text/javascript;base64,' + Buffer.from(backendCompiled).toString('base64'))
const user = (id, role = 'student') => ({ id, account: id, role,
  identity: role === 'admin' ? '管理员' : role === 'teacher' ? '教师' : '学生',
  display_name: id, email: null, email_verified: false })
const result = (id, role) => ({ access_token: 'token-' + id, token_type: 'bearer', expires_in: 900, user: user(id, role) })
const config = { site_key: 'test-key', csrf_token: 'test-csrf', available: true }
const response = body => Response.json(body)
const login = body => session.establishSession(async () => body, value => value.user)
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
for (const bad of [ { ...result('A'), user: undefined }, { ...result('A'), expires_in: 'invalid' }, { ...result('A'), expires_in: Infinity }, { ...result('A'), expires_in: 0 }, result('A', 'unknown'),
  ...[undefined, 'false', 0, null].map(email_verified => ({ ...result('A'), user: { ...user('A'), email_verified } })),
]) {
  await assert.rejects(login(bad))
  assert.equal(session.getApiToken(), '')
}
for (const role of ['student', 'teacher', 'admin']) {
  await login(result('role-check', role))
  assert.equal(session.getApiToken(), 'token-role-check')
}
session.clearSession()
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
  const oldEntered = deferred(), oldResponse = deferred()
  const freshEntered = deferred(), freshResponse = deferred()
  let refreshRequests = 0
  globalThis.fetch = async path => {
    if (path.endsWith('/config')) return response(config)
    refreshRequests += 1
    if (refreshRequests === 1) { oldEntered.resolve(); return oldResponse.promise }
    assert.equal(refreshRequests, 2, '新代次应始终保持一个刷新请求')
    freshEntered.resolve(); return freshResponse.promise
  }
  controlledLocks = true
  try {
    const old = session.refreshSession()
    const rejected = assert.rejects(old, error => error.code === (success ? 'SESSION_ENDED' : 'REQUEST_FAILED'))
    runScheduledLock()
    await oldEntered.promise
    TestChannel.listener({ data: { type: 'invalidate', scope: 'user', userId: 'A' } })
    const newLogin = login(result('C'))
    runScheduledLock()
    await newLogin
    assert.equal(session.getApiToken(), 'token-C', '旧响应释放前，新账号必须已安装')
    const fresh = session.refreshSession()
    runScheduledLock()
    await freshEntered.promise
    const clearedBeforeOldCompletion = cleared
    oldResponse.resolve(success ? response(result('A')) : Response.json({}, { status: 401 }))
    await rejected // 已等待旧 catch 和 finally 全部执行。
    assert.equal(session.getApiToken(), 'token-C', '旧 catch 不得清除新代次 token')
    assert.equal(cleared, clearedBeforeOldCompletion, '旧 catch 不得通知清理新用户上下文')
    const follower = session.refreshSession()
    assert.equal(scheduledLocks.length, 0, '旧 finally 不得释放新代次单飞槽位')
    assert.equal(refreshRequests, 2, '后续调用应复用尚未完成的新刷新')
    freshResponse.resolve(response({ ...result('C'), access_token: 'token-C-refreshed' }))
    await Promise.all([fresh, follower])
    assert.equal(session.getApiToken(), 'token-C-refreshed')
    assert.equal(scheduledLocks.length, 0)
  } finally { controlledLocks = false }
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

// 必须走真实 uploadDocument / authenticatedOperation，而非单独测试伪造的重试器。
class TestXHR {
  static requests = []
  static sendAction
  upload = {}
  headers = new Headers()
  status = 0
  responseText = ''
  open(method, path) { this.method = method; this.path = path }
  setRequestHeader(name, value) { this.headers.set(name, value) }
  send(body) {
    this.body = body
    TestXHR.requests.push(this)
    TestXHR.sendAction(this)
  }
  respond(status, body) {
    this.status = status
    this.responseText = JSON.stringify(body)
    this.onload()
  }
}
globalThis.XMLHttpRequest = TestXHR
const uploadFile = new Blob(['synthetic upload regression'], { type: 'text/plain' })
const uploaded = { document_id: 'document-A', status: 'pending', stage: 'uploaded', progress: 0 }
const authFailure = code => ({ detail: { code, message: code } })
let uploadRefreshes = 0
async function prepareUpload(auth = result('A'), refreshed = result('A')) {
  await login(auth)
  uploadRefreshes = 0
  TestXHR.requests = []
  globalThis.fetch = async path => {
    if (path === '/api/auth/config') return response(config)
    assert.equal(path, '/api/auth/refresh', '上传认证只能访问合成刷新端点')
    uploadRefreshes += 1
    return response(refreshed)
  }
}
function uploadRequestAssertions(xhr, bearer) {
  assert.equal(xhr.method, 'POST')
  assert.equal(xhr.path, '/api/banks/bank-A/documents')
  assert.equal(xhr.withCredentials, true)
  assert.equal(xhr.headers.get('Authorization'), bearer)
  assert.equal(xhr.headers.has('Content-Type'), false, 'multipart boundary 应由浏览器生成')
  assert.ok(xhr.body instanceof FormData)
  assert.equal(xhr.body.get('file').size, uploadFile.size)
}

// 令牌临近过期时先续期，再创建 XHR，不发送已知过期的 token。
await prepareUpload({ ...result('A'), expires_in: 1 }, { ...result('A'), access_token: 'token-A-preflight' })
TestXHR.sendAction = xhr => {
  assert.equal(uploadRefreshes, 1, '发送上传前必须完成预刷新')
  uploadRequestAssertions(xhr, 'Bearer token-A-preflight')
  xhr.respond(200, uploaded)
}
assert.deepEqual(await uploadDocument('bank-A', uploadFile), uploaded)
assert.equal(TestXHR.requests.length, 1)

// 明确的 401 ACCESS_TOKEN_EXPIRED 才允许刷新并重试一次，保留两次的进度回调。
await prepareUpload(result('A'), { ...result('A'), access_token: 'token-A-refreshed' })
const uploadProgress = []
TestXHR.sendAction = xhr => {
  const first = TestXHR.requests.length === 1
  uploadRequestAssertions(xhr, first ? 'Bearer token-A' : 'Bearer token-A-refreshed')
  xhr.upload.onprogress({ lengthComputable: false, loaded: 1, total: 0 })
  xhr.upload.onprogress({ lengthComputable: true, loaded: first ? 1 : 4, total: 4 })
  xhr.respond(first ? 401 : 200, first ? authFailure('ACCESS_TOKEN_EXPIRED') : uploaded)
}
assert.deepEqual(await uploadDocument('bank-A', uploadFile, percent => uploadProgress.push(percent)), uploaded)
assert.equal(uploadRefreshes, 1)
assert.equal(TestXHR.requests.length, 2)
assert.deepEqual(uploadProgress, [25, 100])
assert.equal(await TestXHR.requests[1].body.get('file').text(), await uploadFile.text())

// 第二次上传仍过期时停止；不能循环刷新，也不能重放第三次写入。
await prepareUpload()
TestXHR.sendAction = xhr => xhr.respond(401, authFailure('ACCESS_TOKEN_EXPIRED'))
await assert.rejects(uploadDocument('bank-A', uploadFile), error => error instanceof session.ApiError && error.status === 401)
assert.equal(uploadRefreshes, 1)
assert.equal(TestXHR.requests.length, 2)

// 撤销、非401的同名错误、未知401均不刷新或重放；错误保留HTTP状态及业务码。
for (const [status, code] of [[401, 'SESSION_REVOKED'], [403, 'ACCESS_TOKEN_EXPIRED'], [401, 'UNAUTHORIZED']]) {
  await prepareUpload()
  TestXHR.sendAction = xhr => xhr.respond(status, authFailure(code))
  await assert.rejects(uploadDocument('bank-A', uploadFile), error => error instanceof session.ApiError && error.code === code && error.status === status)
  assert.equal(uploadRefreshes, 0)
  assert.equal(TestXHR.requests.length, 1)
}

// 刷新Cookie若属于另一用户或角色，不以新身份重放旧上传。
for (const changedIdentity of [result('B'), result('A', 'teacher')]) {
  await prepareUpload(result('A'), changedIdentity)
  TestXHR.sendAction = xhr => xhr.respond(401, authFailure('ACCESS_TOKEN_EXPIRED'))
  await assert.rejects(uploadDocument('bank-A', uploadFile), error => error.code === 'SESSION_IDENTITY_CHANGED')
  assert.equal(uploadRefreshes, 1)
  assert.equal(TestXHR.requests.length, 1)
  assert.equal(session.getApiToken(), '')
}

// 本地身份切换/退出/跨标签失效发生后，旧401不续期；旧成功体也不能交给新身份。
for (const endSession of [async () => { await login(result('C')) }, async () => { session.clearSession() },
  async () => { TestChannel.listener({ data: { type: 'invalidate', scope: 'user', userId: 'A' } }) }]) {
  for (const status of [401, 200]) {
    await prepareUpload()
    const entered = deferred()
    TestXHR.sendAction = xhr => entered.resolve(xhr)
    const upload = uploadDocument('bank-A', uploadFile)
    const rejection = assert.rejects(upload, error => error instanceof session.ApiError && error.code === 'SESSION_ENDED')
    const xhr = await entered.promise
    await endSession()
    const newToken = session.getApiToken()
    const clearedBeforeResponse = cleared
    xhr.respond(status, status === 200 ? uploaded : authFailure('ACCESS_TOKEN_EXPIRED'))
    await rejection
    assert.equal(uploadRefreshes, 0)
    assert.equal(TestXHR.requests.length, 1)
    assert.equal(session.getApiToken(), newToken, '旧上传不得清除新身份凭据')
    assert.equal(cleared, clearedBeforeResponse, '旧上传不得清理新代次上下文')
  }
}
console.log('PASS: actual uploadDocument preflight, one expired retry + progress, revoked no replay, identity and stale success isolation')

// 新建并上传是独立写接口，必须验证其实际 XHR 错误解析及会话保护。
const createdBank = {
  bank: { id: 'bank-A', name: '合成题库', code: 'fake-code', creator: { id: 'A', display_name: 'A' },
    member_count: 1, capacity: 100, source: 'owned', quitted: false, my_role: 'creator',
    can_upload_document: true, can_download_document: true, can_delete_document: true,
    can_manage_members: true, can_edit_bank: true, can_transfer_bank: false, can_delete_bank: true },
  document: { document_id: 'document-A', name: 'synthetic.txt', eta_minutes: 3, status: 'uploaded' },
}
function creationAssertions(xhr, bearer) {
  assert.equal(xhr.method, 'POST')
  assert.equal(xhr.path, '/api/banks/with-document')
  assert.equal(xhr.withCredentials, true)
  assert.equal(xhr.headers.get('Authorization'), bearer)
  assert.equal(xhr.headers.has('Content-Type'), false)
  assert.equal(xhr.body.get('name'), '合成题库')
  assert.equal(xhr.body.get('file').size, uploadFile.size)
}
const teacher = result('A', 'teacher')
await prepareUpload({ ...teacher, expires_in: 1 }, { ...teacher, access_token: 'token-A-preflight' })
TestXHR.sendAction = xhr => {
  assert.equal(uploadRefreshes, 1)
  creationAssertions(xhr, 'Bearer token-A-preflight')
  xhr.respond(201, createdBank)
}
assert.deepEqual(await createBankWithDocument('合成题库', uploadFile), createdBank)
assert.equal(TestXHR.requests.length, 1)

await prepareUpload(teacher, { ...teacher, access_token: 'token-A-refreshed' })
const creationProgress = []
TestXHR.sendAction = xhr => {
  const first = TestXHR.requests.length === 1
  creationAssertions(xhr, first ? 'Bearer token-A' : 'Bearer token-A-refreshed')
  xhr.upload.onprogress({ lengthComputable: true, loaded: first ? 1 : 4, total: 4 })
  xhr.respond(first ? 401 : 201, first ? authFailure('ACCESS_TOKEN_EXPIRED') : createdBank)
}
assert.deepEqual(await createBankWithDocument('合成题库', uploadFile, value => creationProgress.push(value)), createdBank)
assert.deepEqual(creationProgress, [25, 100])
assert.equal(uploadRefreshes, 1)
assert.equal(TestXHR.requests.length, 2)

for (const [status, code] of [[401, 'SESSION_REVOKED'], [403, 'ACCESS_TOKEN_EXPIRED'], [401, 'UNAUTHORIZED']]) {
  await prepareUpload(teacher, teacher)
  TestXHR.sendAction = xhr => xhr.respond(status, authFailure(code))
  await assert.rejects(createBankWithDocument('合成题库', uploadFile), error => error.code === code && error.status === status)
  assert.equal(uploadRefreshes, 0)
  assert.equal(TestXHR.requests.length, 1)
}
await prepareUpload(teacher, teacher)
TestXHR.sendAction = xhr => xhr.respond(401, authFailure('ACCESS_TOKEN_EXPIRED'))
await assert.rejects(createBankWithDocument('合成题库', uploadFile), error => error.status === 401)
assert.equal(uploadRefreshes, 1)
assert.equal(TestXHR.requests.length, 2)

for (const changedIdentity of [result('B', 'teacher'), result('A', 'student')]) {
  await prepareUpload(teacher, changedIdentity)
  TestXHR.sendAction = xhr => xhr.respond(401, authFailure('ACCESS_TOKEN_EXPIRED'))
  await assert.rejects(createBankWithDocument('合成题库', uploadFile), error => error.code === 'SESSION_IDENTITY_CHANGED')
  assert.equal(TestXHR.requests.length, 1)
}
for (const status of [201, 401]) {
  await prepareUpload(teacher, teacher)
  const entered = deferred()
  TestXHR.sendAction = xhr => entered.resolve(xhr)
  const creation = createBankWithDocument('合成题库', uploadFile)
  const rejection = assert.rejects(creation, error => error.code === 'SESSION_ENDED')
  const xhr = await entered.promise
  await login(result('B', 'teacher'))
  xhr.respond(status, status === 201 ? createdBank : authFailure('ACCESS_TOKEN_EXPIRED'))
  await rejection
  assert.equal(TestXHR.requests.length, 1)
  assert.equal(uploadRefreshes, 0)
  assert.equal(session.getApiToken(), 'token-B')
}
for (const malformed of [{}, { ...createdBank, bank: { ...createdBank.bank, my_role: 'owner' } },
  { ...createdBank, document: { ...createdBank.document, eta_minutes: 'invalid' } }]) {
  await prepareUpload(teacher, teacher)
  TestXHR.sendAction = xhr => xhr.respond(201, malformed)
  await assert.rejects(createBankWithDocument('合成题库', uploadFile), error => error.code === 'REQUEST_FAILED')
  assert.equal(TestXHR.requests.length, 1)
}
console.log('PASS: actual createBankWithDocument preflight, one expired retry, revoked no replay, stale identity and response contract')
