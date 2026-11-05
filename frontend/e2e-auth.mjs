/* global process, localStorage, URL, console, window, document, setTimeout */
/** 浏览器/HTTP 接缝：合成数据、假邮件与 Siteverify，不连接真实后端。 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { join } from 'node:path'
import { homedir, tmpdir } from 'node:os'
const require = createRequire(join(tmpdir(), 'mathcraft-auth-browser', 'package.json'))
const { chromium } = require('playwright-core')
const browser = await chromium.launch({ executablePath: process.env.AUTH_BROWSER ?? join(homedir(), 'AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe'), headless: true })
const origin = process.env.AUTH_TEST_URL ?? 'http://127.0.0.1:5178'
const initialUser = { id: 'test-user', account: 'internal-only', role: 'student', identity: '学生', display_name: '测试同学', email: 'student@example.test', user_no: null }
const context = await browser.newContext()
let user = { ...initialUser }, signedIn = false, devEnabled = false, rejectReset = true
let refreshes = 0, activeRefresh = 0, maximumRefresh = 0, accountRequests = 0
const calls = [], errors = []
await context.addInitScript(() => localStorage.setItem('mathcraft-auth', JSON.stringify({ token: 'obsolete-test-token' })))
await context.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname
  if (!path.startsWith('/api/')) return route.continue()
  const bodyIn = request.postData() ? request.postDataJSON() : null
  calls.push({ path, body: bodyIn, method: request.method() })
  let status = 200, body
  if (path === '/api/test/retry') {
    const attempts = calls.filter(call => call.path === path).length
    if (attempts === 1) { status = 401; body = { detail: { code: 'ACCESS_TOKEN_EXPIRED', message: 'expired test access' } } }
    else body = { ok: true }
  } else if (path === '/api/test/rejected') {
    status = 401; body = { detail: { code: 'SESSION_REVOKED', message: 'revoked test session' } }
  } else if (path === '/api/auth/config') body = { site_key: 'test-site-key', csrf_token: 'test-csrf', development_accounts_enabled: devEnabled, available: true }
  else if (path === '/api/auth/refresh') {
    assert.equal(request.headers()['x-csrf-token'], 'test-csrf')
    assert.deepEqual(bodyIn, {})
    refreshes++; activeRefresh++; maximumRefresh = Math.max(maximumRefresh, activeRefresh)
    await new Promise(resolve => setTimeout(resolve, 60))
    activeRefresh--
    if (!signedIn) { status = 401; body = { detail: { code: 'TOKEN_EXPIRED', message: '请登录' } } }
    else body = { access_token: 'test-refreshed', token_type: 'bearer', expires_in: 900, user }
  } else if (path === '/api/auth/email-code') {
    assert.equal(bodyIn.turnstile_token, 'test-turnstile')
    if (bodyIn.purpose.startsWith('email_change')) assert.equal(bodyIn.change_id, 'change-test')
    body = { challenge_id: 'challenge-' + bodyIn.purpose, expires_in: 300, retry_after: 60 }
  } else if (path === '/api/auth/register') {
    assert.deepEqual(bodyIn, { email: 'student@example.test', challenge_id: 'challenge-register', code: '123456', password: 'Test-only-123', confirm_password: 'Test-only-123', display_name: '测试同学', role: 'student', user_no: null })
    signedIn = true
    body = { access_token: 'test-access', token_type: 'bearer', expires_in: 900, user }
  } else if (path === '/api/auth/login/email') {
    assert.equal(bodyIn.role, 'student'); assert.equal(bodyIn.challenge_id, 'challenge-login')
    signedIn = true; body = { access_token: 'test-access', token_type: 'bearer', expires_in: 900, user }
  } else if (path === '/api/auth/login/password') {
    assert.equal(bodyIn.user_no, '00042'); assert.equal(bodyIn.turnstile_token, 'test-turnstile')
    signedIn = true; body = { access_token: 'test-access', token_type: 'bearer', expires_in: 900, user }
  } else if (path === '/api/auth/password/reset') {
    assert.deepEqual(bodyIn, { email: 'student@example.test', challenge_id: 'challenge-reset_password', code: rejectReset ? '000000' : '123456', new_password: 'Reset-only-123', confirm_password: 'Reset-only-123' })
    if (rejectReset) { status = 400; body = { detail: { code: 'CODE_INVALID', message: '验证码错误' } } }
    else { signedIn = false; status = 204 }
  } else if (path === '/api/auth/password') {
    assert.deepEqual(bodyIn, { old_password: 'Test-only-123', new_password: 'Changed-only-123', confirm_password: 'Changed-only-123' })
    signedIn = false; status = 204
  } else if (path === '/api/users/me/user-no') {
    assert.deepEqual(bodyIn, { user_no: '00042', current_password: 'Test-only-123' })
    user = { ...user, user_no: bodyIn.user_no }; body = user
  } else if (path === '/api/users/me/email-change') {
    assert.deepEqual(bodyIn, { new_email: 'new@example.test' }); body = { change_id: 'change-test', expires_in: 600 }
  } else if (path === '/api/users/me/email') {
    assert.deepEqual(bodyIn, { change_id: 'change-test', old_challenge_id: 'challenge-email_change_old', old_code: '123456', new_challenge_id: 'challenge-email_change_new', new_code: '654321' })
    signedIn = false; user = { ...user, email: 'new@example.test' }; status = 204
  } else if (path === '/api/auth/development-account') {
    accountRequests++; body = { role: url.searchParams.get('role'), user_no: '00042', password: 'Test-only-123' }
  } else if (path === '/api/auth/logout') {
    assert.equal(request.headers()['x-csrf-token'], 'test-csrf'); signedIn = false; status = 204
  } else if (path === '/api/auth/me') body = { user }
  else if (path.includes('model-settings')) body = { mineru_limits: {}, embedding_model: 'test', rerank_model: 'test' }
  else body = []
  await route.fulfill({ status, contentType: 'application/json', ...(status === 204 ? {} : { body: JSON.stringify(body) }) })
})
await context.route('https://challenges.cloudflare.com/**', route => route.fulfill({ contentType: 'application/javascript', body: 'window.turnstile={render:(el,opts)=>{setTimeout(()=>opts.callback("test-turnstile"),0);return "widget"},remove:()=>{}}' }))
const page = await context.newPage()
page.on('pageerror', error => errors.push(error.message))
async function openLogin() { await page.goto(origin); await page.getByRole('button', { name: '注册账号', exact: true }).waitFor() }
async function workspace() { await page.waitForSelector('.stage', { state: 'detached' }) }
async function loginEmail() {
  await page.getByRole('button', { name: '邮箱码登录', exact: true }).click()
  await page.getByLabel('邮箱', { exact: true }).fill('student@example.test')
  await page.getByRole('button', { name: '发送验证码', exact: true }).click()
  await page.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await page.getByRole('button', { name: '登录并进入工作台', exact: true }).click(); await workspace()
}
async function profile() { await page.getByRole('button', { name: '个人中心', exact: true }).click() }
try {
  await openLogin()
  await page.getByRole('button', { name: '注册账号', exact: true }).click()
  await page.getByLabel('邮箱', { exact: true }).fill('student@example.test')
  await page.getByLabel('显示名称').fill('测试同学')
  await page.getByLabel('密码', { exact: true }).fill('Test-only-123')
  await page.getByLabel('确认密码', { exact: true }).fill('Test-only-123')
  await page.getByRole('button', { name: '发送验证码', exact: true }).click()
  await page.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await page.getByRole('button', { name: '注册并进入工作台', exact: true }).click(); await workspace()
  assert.equal(await page.evaluate(() => localStorage.getItem('mathcraft-auth')), null)
  assert.equal(await page.evaluate(() => JSON.stringify(localStorage)), '{}')
  console.log('PASS 注册直达工作台；确认密码契约；旧凭据清理；access 不持久化')
  const beforeRetry = refreshes
  const retryStatus = await page.evaluate(async () => {
    const { sessionFetch, setApiToken } = await import('/src/api/session.ts')
    setApiToken('test-http-seam-access', 900)
    return (await sessionFetch('/api/test/retry', { method: 'POST', body: '{}' })).status
  })
  assert.equal(retryStatus, 200)
  assert.equal(refreshes, beforeRetry + 1)
  assert.equal(calls.filter(call => call.path === '/api/test/retry').length, 2)
  const beforeRejection = refreshes
  await page.evaluate(async () => {
    const { sessionFetch, setApiToken } = await import('/src/api/session.ts')
    setApiToken('test-http-seam-access', 900)
    try { await sessionFetch('/api/test/rejected', { method: 'POST', body: '{}' }) } catch { /* 会话撤销须终止。 */ }
  })
  assert.equal(refreshes, beforeRejection)
  assert.equal(calls.filter(call => call.path === '/api/test/rejected').length, 1)
  console.log('PASS 明确过期只重放一次写请求；撤销会话不刷新、不重放')
  await page.reload(); await workspace()
  const peer = await context.newPage(); await Promise.all([page.reload(), peer.goto(origin)])
  await peer.waitForSelector('.stage', { state: 'detached' }); await workspace()
  assert.equal(maximumRefresh, 1)
  console.log('PASS 页面恢复；双标签刷新串行且无凭据广播')
  await profile()
  await page.getByLabel('学工号', { exact: true }).fill('00042')
  await page.getByLabel('当前密码', { exact: true }).fill('Test-only-123')
  await page.getByRole('button', { name: '保存学工号', exact: true }).click()
  await page.getByText('学工号已更新；仍可使用邮箱验证码登录').waitFor()
  assert.equal(await page.getByLabel('当前密码', { exact: true }).inputValue(), '')
  await page.getByRole('button', { name: '修改密码', exact: true }).click()
  await page.getByLabel('当前密码', { exact: true }).last().fill('Test-only-123')
  await page.getByLabel('新密码', { exact: true }).fill('Changed-only-123')
  await page.getByLabel('确认新密码', { exact: true }).fill('Changed-only-123')
  await page.getByRole('button', { name: '确认修改', exact: true }).click()
  await page.getByRole('button', { name: '注册账号', exact: true }).waitFor()
  await peer.getByRole('button', { name: '注册账号', exact: true }).waitFor(); await peer.close()
  console.log('PASS 学工号前导零及直接 user 响应；改密确认字段；跨标签退出')
  await page.getByRole('button', { name: '忘记密码？', exact: true }).click()
  await page.getByLabel('邮箱', { exact: true }).fill('student@example.test')
  await page.getByLabel('新密码', { exact: true }).fill('Reset-only-123')
  await page.getByLabel('确认新密码', { exact: true }).fill('Reset-only-123')
  await page.getByRole('button', { name: '发送验证码', exact: true }).click()
  await page.getByLabel('邮箱验证码', { exact: true }).fill('000000')
  await page.getByRole('button', { name: '重置密码', exact: true }).click()
  await page.getByText('验证码错误', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('新密码', { exact: true }).inputValue(), 'Reset-only-123')
  assert.equal(await page.getByLabel('确认新密码', { exact: true }).inputValue(), 'Reset-only-123')
  rejectReset = false
  await page.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await page.getByRole('button', { name: '重置密码', exact: true }).click()
  await page.getByText('密码已重置，所有设备已下线，请重新登录').waitFor()
  console.log('PASS 错误验证码保留两个密码；reset 无 role；成功返回登录')
  await loginEmail(); await profile()
  await page.getByLabel('新邮箱', { exact: true }).fill('new@example.test')
  await page.getByRole('button', { name: '开始换绑', exact: true }).click()
  await page.getByRole('button', { name: '发送验证码', exact: true }).nth(0).click()
  await page.getByRole('button', { name: '发送验证码', exact: true }).click()
  await page.getByLabel('旧邮箱验证码', { exact: true }).fill('123456')
  await page.getByLabel('新邮箱验证码', { exact: true }).fill('654321')
  await page.getByRole('button', { name: '确认换绑并重新登录', exact: true }).click()
  await page.getByRole('button', { name: '注册账号', exact: true }).waitFor()
  console.log('PASS 邮箱码登录；双邮箱事务收件人及 change_id；换绑退出')
  devEnabled = true; await openLogin()
  const before = calls.filter(call => call.path === '/api/auth/login/password').length
  await page.getByRole('button', { name: '填充学生开发账号', exact: true }).click()
  await page.getByText('已填充开发账号，请完成人机验证后手动登录').waitFor()
  assert.equal(calls.filter(call => call.path === '/api/auth/login/password').length, before)
  assert.equal(accountRequests, 1)
  await page.getByRole('button', { name: '登录并进入工作台', exact: true }).click(); await workspace()
  console.log('PASS 开发按钮只填充；正常学工号/密码/Turnstile 登录')
  signedIn = false; devEnabled = false; await openLogin()
  await page.setViewportSize({ width: 375, height: 812 }); await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.getByRole('button', { name: '注册账号', exact: true }).click()
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
  await page.screenshot({ path: join(tmpdir(), 'mathcraft-auth-mobile.png'), fullPage: true })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.screenshot({ path: join(tmpdir(), 'mathcraft-auth-desktop.png'), fullPage: true })
  assert.deepEqual(errors, [])
  console.log('PASS 375px 注册无横向溢出；减少动画；无浏览器异常；截图在临时目录')
  console.log('Browser authentication checks complete; refresh requests:', refreshes)
} finally { await browser.close() }
