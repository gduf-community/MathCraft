/* global process, localStorage, URL, console, window, document, navigator, setTimeout */
/** 真实前端浏览器回归：仅使用内存 API 与假 Turnstile，不连接后端。 */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { join } from 'node:path'
import { homedir, tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
const require = createRequire(join(tmpdir(), 'mathcraft-auth-browser', 'package.json'))
const { chromium } = require('playwright-core')
const browser = await chromium.launch({ executablePath: process.env.AUTH_BROWSER ?? join(homedir(), 'AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe'), headless: true })
const origin = process.env.AUTH_TEST_URL ?? 'http://127.0.0.1:5178'
const artifacts = fileURLToPath(new URL('../output/playwright/auth-account/', import.meta.url))
await mkdir(artifacts, { recursive: true })
const fixture = (role = 'student', verified = false) => ({ id: 'test-' + role, account: 'fake-' + role, role,
  identity: role === 'admin' ? '管理员' : role === 'teacher' ? '教师' : '学生',
  display_name: '测试' + role, email: verified ? role + '@example.test' : null,
  email_verified: verified, user_no: null, password_change_recommended: false })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce', serviceWorkers: 'block' })
let user = fixture(), signedIn = false, devEnabled = false, rejectReset = true, rejectMutation = false
let turnstileEnabled, authAvailable = true, cloudflareRequests = 0, rejectLogout = false
let emailCodeGate = Promise.resolve(), rejectBindingCode = false
let refreshes = 0, activeRefresh = 0, maximumRefresh = 0, accountRequests = 0
const calls = [], errors = [], unexpected = []
const loginResult = () => ({ access_token: 'test-access', token_type: 'bearer', expires_in: 900, user })
await context.addInitScript(expected => {
  if (window.location.origin === expected) localStorage.setItem('mathcraft-auth', JSON.stringify({ token: 'obsolete-test-token' }))
}, origin)
// 所有 HTTP 均拦截；只允许本地 Vite 资源，其余请求不会离开浏览器。
await context.route('**/*', async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname
  if (url.hostname === 'challenges.cloudflare.com') {
    cloudflareRequests++
    return route.fulfill({ contentType: 'application/javascript', body: 'window.turnstile={render:(el,opts)=>{setTimeout(()=>opts.callback("test-turnstile"),0);return "widget"},remove:()=>{}}' })
  }
  if (!path.startsWith('/api/')) {
    if (url.origin === origin) return route.continue()
    unexpected.push(request.method() + ' ' + url.origin + path)
    return route.abort()
  }
  const bodyIn = request.postData() ? request.postDataJSON() : null, method = request.method()
  calls.push({ path, body: bodyIn, method })
  const authenticated = () => assert.equal(request.headers().authorization, 'Bearer test-access')
  let status = 200, body
  if (path === '/api/test/retry') {
    if (calls.filter(call => call.path === path).length === 1) { status = 401; body = { detail: { code: 'ACCESS_TOKEN_EXPIRED', message: 'expired test access' } } }
    else body = { ok: true }
  } else if (path === '/api/auth/config') body = { site_key: turnstileEnabled === false ? '' : 'test-site-key', csrf_token: 'test-csrf', development_accounts_enabled: devEnabled, available: authAvailable, methods: ['account_password', 'email_code'], admin_contact: '测试管理员', ...(turnstileEnabled === undefined ? {} : { turnstile_enabled: turnstileEnabled }) }
  else if (path === '/api/auth/refresh') {
    assert.equal(request.headers()['x-csrf-token'], 'test-csrf'); assert.deepEqual(bodyIn, {})
    refreshes++; activeRefresh++; maximumRefresh = Math.max(maximumRefresh, activeRefresh)
    await new Promise(resolve => setTimeout(resolve, 60)); activeRefresh--
    if (!signedIn) { status = 401; body = { detail: { code: 'TOKEN_EXPIRED', message: '请登录' } } }
    else body = loginResult()
  } else if (path === '/api/auth/email-code') {
    assert.equal(method, 'POST'); assert.equal(bodyIn.turnstile_token, turnstileEnabled === false ? '' : 'test-turnstile')
    assert.ok(['login', 'reset_password', 'email_bind', 'email_change_old', 'email_change_new'].includes(bodyIn.purpose))
    if (bodyIn.purpose === 'email_bind' || bodyIn.purpose.startsWith('email_change')) authenticated()
    else assert.equal(request.headers().authorization, undefined)
    if (bodyIn.purpose === 'email_bind') await emailCodeGate
    if (bodyIn.purpose.startsWith('email_change')) {
      assert.equal(bodyIn.change_id, 'change-test')
      assert.equal(bodyIn.email, bodyIn.purpose === 'email_change_old' ? user.email : 'new@example.test')
    }
    if (bodyIn.purpose === 'email_bind' && rejectBindingCode) {
      status = 503; body = { detail: { code: 'UNAVAILABLE', message: '测试绑定验证码发送失败，请重试' } }
    } else { status = 202; body = { challenge_id: 'challenge-' + bodyIn.purpose, expires_in: 300, retry_after: 60 } }
  } else if (path === '/api/auth/login/account') {
    assert.equal(method, 'POST')
    assert.deepEqual(bodyIn, { account: user.account, password: bodyIn.password, turnstile_token: turnstileEnabled === false ? '' : 'test-turnstile' })
    assert.equal(typeof bodyIn.password, 'string')
    if (bodyIn.password !== 'Test-only-123') { status = 401; body = { detail: { code: 'PASSWORD_INVALID', message: '账号或密码错误' } } }
    else { signedIn = true; body = loginResult() }
  } else if (path === '/api/auth/login/email') {
    assert.equal(method, 'POST'); assert.ok(user.email_verified)
    assert.deepEqual(bodyIn, { email: user.email, challenge_id: 'challenge-login', code: bodyIn.code })
    if (bodyIn.code !== '123456') { status = 400; body = { detail: { code: 'CODE_INVALID', message: '验证码错误' } } }
    else { signedIn = true; body = loginResult() }
  } else if (path === '/api/auth/password/reset') {
    assert.deepEqual(bodyIn, { email: user.email, challenge_id: 'challenge-reset_password', code: rejectReset ? '000000' : '123456', new_password: 'Reset-only-123', confirm_password: 'Reset-only-123' })
    if (rejectReset) { status = 400; body = { detail: { code: 'CODE_INVALID', message: '验证码错误' } } }
    else { signedIn = false; status = 204 }
  } else if (path === '/api/auth/password') {
    authenticated(); assert.equal(method, 'PUT')
    assert.deepEqual(bodyIn, { old_password: 'Test-only-123', new_password: 'Changed-only-123', confirm_password: 'Changed-only-123' })
    signedIn = false; status = 204
  } else if (path === '/api/users/me/user-no') {
    authenticated(); assert.equal(method, 'PUT')
    assert.deepEqual(bodyIn, { user_no: '00042', current_password: 'Test-only-123' })
    user = { ...user, user_no: bodyIn.user_no }; body = user
  } else if (path === '/api/users/me/email-binding') {
    authenticated(); assert.equal(method, 'PUT')
    assert.deepEqual(bodyIn, { email: 'bound@example.test', challenge_id: 'challenge-email_bind', code: rejectMutation ? '000000' : '123456' })
    if (rejectMutation) { status = 400; body = { detail: { code: 'CODE_INVALID', message: '验证码错误' } } }
    else { signedIn = false; user = { ...user, email: bodyIn.email, email_verified: true }; status = 204 }
  } else if (path === '/api/users/me/email-change') {
    authenticated(); assert.equal(method, 'POST'); assert.deepEqual(bodyIn, { new_email: 'new@example.test' })
    body = { change_id: 'change-test', expires_in: 600 }
  } else if (path === '/api/users/me/email') {
    authenticated()
    if (method === 'DELETE') {
      assert.deepEqual(bodyIn, { current_password: 'Test-only-123' })
      signedIn = false; user = { ...user, email: null, email_verified: false }; status = 204
    } else {
      assert.equal(method, 'PUT')
      assert.deepEqual(bodyIn, { change_id: 'change-test', old_challenge_id: 'challenge-email_change_old', old_code: '123456', new_challenge_id: 'challenge-email_change_new', new_code: '654321' })
      signedIn = false; user = { ...user, email: 'new@example.test', email_verified: true }; status = 204
    }
  } else if (path === '/api/auth/development-account') {
    assert.equal(method, 'POST'); assert.deepEqual(bodyIn, {})
    accountRequests++; const role = url.searchParams.get('role'); assert.ok(['student', 'teacher'].includes(role))
    user = fixture(role); body = { account: user.account, password: 'Test-only-123' }
  } else if (path === '/api/auth/logout') {
    authenticated(); assert.equal(request.headers()['x-csrf-token'], 'test-csrf')
    if (rejectLogout) { status = 503; body = { detail: { code: 'UNAVAILABLE', message: '测试退出暂不可用' } } }
    else { signedIn = false; status = 204 }
  } else if (path === '/api/auth/me') { authenticated(); body = { user } }
  else if (path === '/api/admin/overview') body = { accounts: { admin_active: 1 }, resources: {}, task_status_counts: {}, tasks: [], task_total: 0, recent_task_limit: 50, admin_contact: '测试管理员' }
  else if (path === '/api/admin/accounts') body = []
  else if (path.startsWith('/api/admin/ops/')) { status = 503; body = { detail: { code: 'NOT_INTEGRATED', message: '合成运维服务未接入' } } }
  else if (path.includes('model-settings')) body = { mineru_limits: {}, embedding_model: 'test', rerank_model: 'test' }
  else if (path === '/api/generate/batches/latest') body = null
  else if (path === '/api/urges' || path === '/api/notifications') body = { unread_count: 0, items: [] }
  else if (['/api/banks', '/api/spaces', '/api/papers', '/api/favorites', '/api/favorite-groups'].includes(path)) body = []
  else { unexpected.push(method + ' ' + path); status = 404; body = { detail: 'unexpected fake route' } }
  await route.fulfill({ status, contentType: 'application/json', ...(status === 204 ? {} : { body: JSON.stringify(body) }) })
})
const page = await context.newPage()
await page.clock.install()
context.on('page', next => next.on('pageerror', error => errors.push(error.message)))
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(30000)
page.setDefaultNavigationTimeout(60000)
async function loginScreen(target = page) {
  await target.locator('#login-title').waitFor()
  assert.equal(await target.getByRole('button', { name: /注册|学工号登录|开通账号登录/ }).count(), 0)
  assert.equal(await target.getByRole('radio').count(), 2)
  await target.getByRole('radio', { name: '学生', exact: true }).waitFor()
  await target.getByRole('radio', { name: '教师', exact: true }).waitFor()
  assert.equal(await target.getByRole('button', { name: '修改密码', exact: true }).count(), 0)
  await target.getByRole('button', { name: '邮箱登录', exact: true }).waitFor()
}
async function openLogin() {
  await page.goto(origin); await loginScreen()
  assert.equal(await page.getByRole('dialog').count(), 0)
  assert.equal(await page.getByRole('button', { name: '绑定邮箱', exact: true }).count(), 0, '主卡不提供直接绑定入口')
  assert.equal(await page.getByRole('button', { name: '先绑定', exact: true }).count(), 0)
  await page.getByLabel('登录账号', { exact: true }).waitFor()
}
async function emailLoginDialog() {
  const dialog = page.getByRole('dialog', { name: '邮箱登录', exact: true })
  await dialog.waitFor()
  assert.equal(await page.getByRole('dialog').count(), 1, '邮箱登录与绑定只保留一个弹窗')
  await dialog.getByText('尚未绑定邮箱？先绑定', { exact: true }).waitFor()
  await dialog.getByRole('button', { name: '先绑定', exact: true }).waitFor()
  return dialog
}
async function openLoginBinding() {
  if (await page.getByRole('dialog').count() === 0) await page.getByRole('button', { name: '邮箱登录', exact: true }).click()
  const email = await emailLoginDialog()
  await email.getByRole('button', { name: '先绑定', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '绑定邮箱', exact: true })
  await dialog.waitFor()
  assert.equal(await page.getByRole('dialog').count(), 1)
  assert.equal(await page.getByRole('dialog', { name: '邮箱登录', exact: true }).count(), 0)
  assert.equal(await dialog.getByRole('button', { name: '返回密码登录', exact: true }).count(), 0)
  await dialog.getByRole('button', { name: '返回邮箱登录', exact: true }).waitFor()
  for (const control of [dialog.getByLabel('登录账号', { exact: true }),
    dialog.getByLabel('当前密码', { exact: true }), dialog.getByLabel('新邮箱', { exact: true })]) {
    await control.waitFor()
    assert.equal(await control.isEditable(), true, '初始账号、当前密码和新邮箱均可输入')
  }
  await dialog.getByRole('button', { name: '发送验证码', exact: true }).waitFor()
  assert.equal(await dialog.getByRole('button', { name: '验证账号', exact: true }).count(), 0)
  assert.equal(await dialog.getByLabel('邮箱验证码', { exact: true }).count(), 0, '发码成功前不展示验证码输入')
  assert.equal(await dialog.getByRole('button', { name: '绑定并返回登录', exact: true }).count(), 0, '发码成功前不展示绑定按钮')
  return dialog
}
async function bindingAccountVerified(dialog) {
  await dialog.getByLabel('邮箱验证码', { exact: true }).and(dialog.locator(':enabled')).waitFor()
  assert.equal(await dialog.getByLabel('新邮箱', { exact: true }).isEditable(), true)
  await dialog.getByRole('button', { name: '绑定并返回登录', exact: true }).waitFor()
  assert.equal(await dialog.getByLabel('当前密码', { exact: true }).count(), 0, '账号验证后密码输入移出 DOM')
  assert.equal(await dialog.locator('input[type="password"]').count(), 0)
  assert.equal(await dialog.getByLabel('登录账号', { exact: true }).count(), 0, '账号验证后使用只读摘要')
  await dialog.getByRole('status').filter({ hasText: `账号 ${user.account} 已验证` }).waitFor()
}
async function returnedToEmail() {
  const dialog = await emailLoginDialog()
  assert.equal(await page.getByRole('dialog', { name: '绑定邮箱', exact: true }).count(), 0)
  assert.equal(await dialog.getByLabel('邮箱', { exact: true }).inputValue(), '')
  assert.equal(await dialog.getByLabel('邮箱验证码', { exact: true }).inputValue(), '')
  assert.equal(await dialog.getByLabel('邮箱验证码', { exact: true }).isDisabled(), true)
  assert.equal(signedIn, false)
  await noBusinessSession()
}
async function noBusinessSession() {
  assert.equal(await page.evaluate(async () => {
    const { getApiToken } = await import('/src/api/session.ts'); return getApiToken()
  }), '', '离开临时绑定会话后不得留下业务凭据')
  assert.equal(await page.getByRole('button', { name: '个人中心', exact: true }).count(), 0)
  assert.equal(await page.getByRole('heading', { name: '运维后台', exact: true }).count(), 0)
}
async function noHorizontalOverflow(scope = page) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, '页面不得横向溢出')
  for (const element of await scope.locator('input, button').all()) {
    if (!await element.isVisible()) continue
    const bounds = await element.boundingBox()
    assert.ok(bounds && bounds.x >= -1 && bounds.x + bounds.width <= page.viewportSize().width + 1, '可见输入框和按钮须完整落在视口宽度内')
  }
}
async function scrollReachable(control) {
  await control.scrollIntoViewIfNeeded()
  const bounds = await control.boundingBox()
  assert.ok(bounds && bounds.y >= -1 && bounds.y + bounds.height <= page.viewportSize().height + 1, '短视口内可滚动到完整控件')
}
async function emailFieldsLayout(scope, emailLabel, { codeVisible = true, sendBeforeCode = false } = {}) {
  await noHorizontalOverflow(scope)
  const email = scope.getByLabel(emailLabel, { exact: true })
  const code = scope.getByLabel('邮箱验证码', { exact: true })
  const send = scope.getByRole('button', { name: /^(?:发送验证码|重新发送验证码|\d+ 秒后重发)$/ })
  for (const input of codeVisible ? [email, code] : [email]) {
    assert.equal(await input.evaluate(element => {
      const label = element.closest('label')
      const range = document.createRange()
      range.selectNodeContents(label.querySelector('span') ?? label.firstChild)
      const rects = Array.from(range.getClientRects()).filter(rect => rect.width > 0)
      return new Set(rects.map(rect => Math.round(rect.top))).size === 1
    }), true, '邮箱和验证码标签应保持单行可读')
  }
  if (!codeVisible) {
    assert.equal(await code.count(), 0)
    const [emailBounds, sendBounds] = await Promise.all([email.boundingBox(), send.boundingBox()])
    assert.ok(emailBounds && sendBounds)
    assert.ok(sendBounds.y >= emailBounds.y + emailBounds.height, '初始发码按钮位于新邮箱输入下方')
    return
  }
  const [emailBounds, codeBounds, sendBounds] = await Promise.all([email.boundingBox(), code.boundingBox(), send.boundingBox()])
  assert.ok(emailBounds && codeBounds && sendBounds)
  assert.ok(codeBounds.y >= emailBounds.y + emailBounds.height, '验证码输入应位于邮箱输入下方')
  if (sendBeforeCode) {
    assert.ok(sendBounds.y >= emailBounds.y + emailBounds.height, '登录绑定发码按钮位于新邮箱输入下方')
    assert.ok(codeBounds.y >= sendBounds.y + sendBounds.height, '登录绑定验证码输入位于发码按钮下方')
  } else assert.ok(sendBounds.y >= codeBounds.y + codeBounds.height, '发码按钮应位于验证码输入下方，避免挤压标签')
}
async function closeLoginDialog() {
  const dialog = page.getByRole('dialog')
  if (await dialog.count()) await dialog.getByRole('button', { name: '关闭配置面板', exact: true }).click()
}
async function submitAuthentication() {
  const dialog = page.getByRole('dialog')
  await (await dialog.count() ? dialog.locator('button[type="submit"]') : page.locator('.stage .login-cta[type="submit"]')).click()
}
async function workspace(target = page) {
  if (user.role === 'admin') await target.getByRole('heading', { name: '运维后台', exact: true }).waitFor()
  else await target.getByRole('button', { name: '个人中心', exact: true }).waitFor()
}
async function loginAccount() {
  await closeLoginDialog()
  if (user.role !== 'admin') await page.getByRole('radio', { name: user.role === 'teacher' ? '教师' : '学生', exact: true }).check()
  await page.getByLabel('登录账号', { exact: true }).fill(user.account)
  await page.getByLabel('密码', { exact: true }).fill('Test-only-123')
  await submitAuthentication(); await workspace()
}
async function loginEmail() {
  if (user.role !== 'admin') await page.getByRole('radio', { name: user.role === 'teacher' ? '教师' : '学生', exact: true }).check()
  await page.getByRole('button', { name: '邮箱登录', exact: true }).click()
  await page.getByLabel('邮箱', { exact: true }).fill(user.email)
  await page.getByRole('button', { name: '发送验证码', exact: true }).click()
  await page.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await submitAuthentication(); await workspace()
}
async function security() {
  if (user.role === 'admin') {
    await page.getByRole('navigation', { name: '管理员后台导航' }).getByRole('button', { name: '账号安全', exact: true }).click()
    const details = page.locator('details').filter({ has: page.locator('summary', { hasText: '个人账号安全' }) })
    assert.equal(await details.getAttribute('open'), null, '管理员个人设置默认折叠')
    await page.locator('summary', { hasText: '个人账号安全' }).click()
    await details.getByRole('region', { name: '账号安全', exact: true }).waitFor()
  } else {
    await page.getByRole('button', { name: '个人中心', exact: true }).click()
    await page.getByText('邮箱（可选）', { exact: true }).waitFor()
    await page.getByText('登录账号', { exact: true }).waitFor()
    assert.equal(await page.getByLabel('登录账号', { exact: true }).count(), 0, '登录账号仅展示')
  }
  return page.getByRole('region', { name: '账号安全', exact: true })
}
async function peer() { const next = await context.newPage(); next.setDefaultTimeout(30000); await next.goto(origin); await workspace(next); await page.bringToFront(); return next }
async function revoked(next, notice) {
  await loginScreen(); await page.locator('.auth-notice').filter({ hasText: notice }).waitFor()
  await loginScreen(next); await next.reload(); await loginScreen(next); await next.close()
  assert.equal(await page.evaluate(() => localStorage.getItem('mathcraft-auth')), null)
}
const updatedNotice = '邮箱已更新，所有设备已退出，请使用账号密码重新登录'
try {
  turnstileEnabled = false
  await openLogin()
  const disabledCloudflareRequests = cloudflareRequests
  assert.equal(disabledCloudflareRequests, 0)
  const submitLogin = page.locator('.stage .login-cta[type="submit"]')
  const passwordCalls = () => calls.filter(call => call.path === '/api/auth/login/account').length
  const beforeEmptyPassword = passwordCalls()
  await page.getByLabel('登录账号', { exact: true }).fill(user.account)
  await submitLogin.click()
  assert.equal(passwordCalls(), beforeEmptyPassword, '关闭 Turnstile 后仍禁止空密码提交')
  await page.getByLabel('密码', { exact: true }).fill('Wrong-only-123')
  await submitLogin.click()
  await page.getByText('账号或密码错误', { exact: true }).waitFor()
  assert.equal(signedIn, false)
  assert.equal(passwordCalls(), beforeEmptyPassword + 1)
  await loginScreen()
  // 登录页绑定只借用认证会话，取消必须撤销；失败保留表单，成功返回登录。
  async function verifyBinding(password = 'Test-only-123', openedDialog) {
    const dialog = openedDialog ?? await openLoginBinding()
    await dialog.getByLabel('登录账号', { exact: true }).fill(user.account)
    await dialog.getByLabel('当前密码', { exact: true }).fill(password)
    await dialog.getByLabel('新邮箱', { exact: true }).fill('bound@example.test')
    await dialog.getByRole('button', { name: '发送验证码', exact: true }).click()
    return dialog
  }
  const logoutCalls = () => calls.filter(call => call.path === '/api/auth/logout').length
  const bindingCodeCalls = () => calls.filter(call => call.path === '/api/auth/email-code' && call.body.purpose === 'email_bind').length
  let binding = await openLoginBinding()
  const beforeUnverifiedReturn = logoutCalls()
  await binding.getByRole('button', { name: '返回邮箱登录', exact: true }).click()
  await returnedToEmail()
  assert.equal(logoutCalls(), beforeUnverifiedReturn, '尚未验证账号时返回不创建或撤销会话')
  const beforeWrongBindingPassword = bindingCodeCalls()
  binding = await verifyBinding('Wrong-only-123')
  await binding.getByText('账号或密码错误', { exact: true }).waitFor()
  assert.equal(signedIn, false)
  assert.equal(bindingCodeCalls(), beforeWrongBindingPassword, '账号密码错误不得请求绑定验证码')
  assert.equal(await binding.getByLabel('邮箱验证码', { exact: true }).count(), 0)
  assert.equal(await binding.getByRole('button', { name: '绑定并返回登录', exact: true }).count(), 0)
  await closeLoginDialog()
  rejectBindingCode = true
  const beforeFailedSendPassword = passwordCalls(), beforeFailedSendCode = bindingCodeCalls()
  binding = await verifyBinding()
  await binding.getByText('测试绑定验证码发送失败，请重试', { exact: true }).waitFor()
  assert.equal(passwordCalls(), beforeFailedSendPassword + 1)
  assert.equal(bindingCodeCalls(), beforeFailedSendCode + 1)
  assert.equal(signedIn, true, '发码失败保留已认证的临时会话供重试')
  assert.equal(await binding.getByLabel('当前密码', { exact: true }).count(), 0)
  assert.equal(await binding.locator('input[type="password"]').count(), 0)
  assert.equal(await binding.getByLabel('登录账号', { exact: true }).count(), 0)
  await binding.getByRole('status').filter({ hasText: `账号 ${user.account} 已验证` }).waitFor()
  assert.equal(await binding.getByLabel('新邮箱', { exact: true }).inputValue(), 'bound@example.test')
  assert.equal(await binding.getByLabel('邮箱验证码', { exact: true }).count(), 0)
  assert.equal(await binding.getByRole('button', { name: '绑定并返回登录', exact: true }).count(), 0)
  rejectBindingCode = false
  await binding.getByRole('button', { name: /^(?:发送验证码|重新发送验证码)$/ }).click()
  await bindingAccountVerified(binding)
  assert.equal(passwordCalls(), beforeFailedSendPassword + 1, '发码失败重试不得重复账号认证')
  assert.equal(bindingCodeCalls(), beforeFailedSendCode + 2)
  const bindingSequence = calls.filter(call => call.path === '/api/auth/login/account' || (call.path === '/api/auth/email-code' && call.body.purpose === 'email_bind')).slice(-3)
  assert.deepEqual(bindingSequence.map(call => call.path), ['/api/auth/login/account', '/api/auth/email-code', '/api/auth/email-code'], '一次账号认证后才发码，失败仅重试发码')
  await binding.getByRole('button', { name: '返回邮箱登录', exact: true }).click()
  await returnedToEmail()
  // 冻结浏览器时间后精确推进 59 + 1 秒，断言不会受截图或机器负载影响。
  await page.clock.pauseAt(new Date(await page.evaluate(() => Date.now()) + 1000))
  try {
    const beforeCooldownPassword = passwordCalls(), beforeCooldownCode = bindingCodeCalls()
    binding = await verifyBinding()
    await bindingAccountVerified(binding)
    const cooldown = binding.getByRole('button', { name: /\d+ 秒后重发/ })
    await cooldown.waitFor()
    assert.equal(await cooldown.isDisabled(), true)
    assert.equal(passwordCalls(), beforeCooldownPassword + 1)
    assert.equal(bindingCodeCalls(), beforeCooldownCode + 1, '一次点击只认证一次并发送一次验证码')
    await page.clock.fastForward(59000)
    await binding.getByRole('button', { name: '1 秒后重发', exact: true }).waitFor()
    assert.equal(await cooldown.isDisabled(), true, '59 秒时仍禁止重发')
    await binding.getByLabel('新邮箱', { exact: true }).fill('changed@example.test')
    assert.equal(await cooldown.isDisabled(), true, '改邮箱不能绕过冷却')
    assert.equal(await binding.getByLabel('邮箱验证码', { exact: true }).count(), 0, '改邮箱隐藏旧验证码输入')
    assert.equal(await binding.getByRole('button', { name: '绑定并返回登录', exact: true }).count(), 0, '改邮箱隐藏绑定按钮')
    await cooldown.evaluate(element => element.click())
    assert.equal(bindingCodeCalls(), beforeCooldownCode + 1, '冷却期间点击禁用按钮不发码')
    await binding.getByLabel('新邮箱', { exact: true }).fill('bound@example.test')
    assert.equal(await cooldown.isDisabled(), true, '改回原邮箱也不能绕过冷却')
    await page.clock.fastForward(1000)
    const resend = binding.getByRole('button', { name: /^(?:发送验证码|重新发送验证码)$/ })
    await resend.and(binding.locator(':enabled')).waitFor()
    assert.equal(await cooldown.count(), 0, '60 秒后结束冷却并恢复发码')
    await resend.click()
    await bindingAccountVerified(binding)
    await cooldown.waitFor()
    assert.equal(bindingCodeCalls(), beforeCooldownCode + 2)
    assert.equal(passwordCalls(), beforeCooldownPassword + 1, '冷却后重发复用账号认证')
    await binding.getByRole('button', { name: '返回邮箱登录', exact: true }).click()
    await returnedToEmail()
  } finally { await page.clock.resume() }
  console.log('PASS 登录绑定一次点击先认证后发码；错密码不发码、发码失败仅重试发码；59 秒禁重发、60 秒恢复、改邮箱不绕过冷却')
  // 已建立临时会话后，无论直接返回还是退出失败重试，都必须记住邮箱登录目的地。
  for (const failFirst of [false, true]) {
    binding = await verifyBinding()
    await bindingAccountVerified(binding)
    assert.equal(await binding.getByLabel('当前密码', { exact: true }).count(), 0, '第二步不再收集密码')
    const beforeReturn = logoutCalls()
    rejectLogout = failFirst
    await binding.getByRole('button', { name: '返回邮箱登录', exact: true }).click()
    if (failFirst) {
      await binding.getByRole('button', { name: '重试退出', exact: true }).waitFor()
      assert.equal(await page.getByRole('dialog').count(), 1)
      assert.equal(await page.getByRole('dialog', { name: '邮箱登录', exact: true }).count(), 0)
      assert.equal(await binding.getByLabel('新邮箱', { exact: true }).count(), 0)
      assert.equal(signedIn, true, '撤销失败不能伪报服务端会话已结束')
      await noBusinessSession()
      await page.screenshot({ path: join(artifacts, 'login-binding-return-retry.png'), fullPage: true })
      rejectLogout = false
      await binding.getByRole('button', { name: '重试退出', exact: true }).click()
    }
    await returnedToEmail()
    assert.equal(logoutCalls(), beforeReturn + (failFirst ? 2 : 1))
  }
  await page.screenshot({ path: join(artifacts, 'login-binding-return-email.png'), fullPage: true })
  console.log('PASS 邮箱登录固定绑定入口与唯一弹窗；未验证返回、临时会话返回撤销、503 重试后仍回到邮箱登录')
  binding = await verifyBinding()
  await bindingAccountVerified(binding)
  assert.equal(await page.getByRole('button', { name: '个人中心', exact: true }).count(), 0)
  const beforeBindingCancel = calls.filter(call => call.path === '/api/auth/logout').length
  rejectLogout = true
  await closeLoginDialog()
  await binding.getByRole('button', { name: '重试退出', exact: true }).waitFor()
  assert.equal(await binding.getByLabel('新邮箱', { exact: true }).count(), 0)
  await noBusinessSession()
  rejectLogout = false
  await binding.getByRole('button', { name: '重试退出', exact: true }).click()
  await binding.waitFor({ state: 'detached' })
  assert.equal(signedIn, false)
  assert.equal(await page.getByRole('dialog').count(), 0, '关闭按钮重试成功回到主卡')
  assert.equal(calls.filter(call => call.path === '/api/auth/logout').length, beforeBindingCancel + 2)
  let releaseEmailCode
  emailCodeGate = new Promise(resolve => { releaseEmailCode = resolve })
  const pendingEmailCode = page.waitForRequest(request => new URL(request.url()).pathname === '/api/auth/email-code' && request.postDataJSON()?.purpose === 'email_bind')
  binding = await verifyBinding()
  await pendingEmailCode
  await binding.getByRole('status').filter({ hasText: `账号 ${user.account} 已验证` }).waitFor()
  assert.equal(await binding.getByLabel('当前密码', { exact: true }).count(), 0, '账号认证成功即移除密码，不等待发码完成')
  assert.equal(await binding.locator('input[type="password"]').count(), 0)
  assert.equal(await binding.getByLabel('登录账号', { exact: true }).count(), 0)
  assert.equal(await binding.getByLabel('邮箱验证码', { exact: true }).count(), 0, '发码响应成功前不展示验证码输入')
  assert.equal(await binding.getByRole('button', { name: '绑定并返回登录', exact: true }).count(), 0)
  assert.equal(await binding.getByRole('button', { name: '关闭配置面板', exact: true }).isDisabled(), true, '发送绑定验证码期间禁止关闭弹窗')
  assert.equal(await binding.getByRole('button', { name: '返回邮箱登录', exact: true }).isDisabled(), true)
  await page.keyboard.press('Escape')
  assert.equal(await binding.count(), 1, '发码期间 Escape 不能绕过禁关')
  releaseEmailCode()
  emailCodeGate = Promise.resolve()
  await bindingAccountVerified(binding)
  await binding.getByLabel('邮箱验证码', { exact: true }).fill('000000')
  rejectMutation = true
  await binding.getByRole('button', { name: '绑定并返回登录', exact: true }).click()
  await binding.getByText('验证码错误', { exact: true }).waitFor()
  assert.equal(await binding.getByLabel('新邮箱', { exact: true }).inputValue(), 'bound@example.test')
  assert.equal(await binding.getByLabel('邮箱验证码', { exact: true }).inputValue(), '000000')
  assert.equal(signedIn, true)
  rejectMutation = false
  await binding.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await page.screenshot({ path: join(artifacts, 'login-email-binding.png'), fullPage: true })
  await binding.getByRole('button', { name: '绑定并返回登录', exact: true }).click()
  await binding.waitFor({ state: 'detached' })
  await page.getByText('邮箱已绑定，所有设备已退出，请重新登录', { exact: true }).waitFor()
  assert.equal(signedIn, false)
  assert.equal(user.email, 'bound@example.test')
  assert.equal(await page.getByRole('dialog').count(), 0)
  await page.getByLabel('登录账号', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('密码', { exact: true }).inputValue(), '')
  await noBusinessSession()
  const beforeAlreadyBoundCode = bindingCodeCalls()
  binding = await verifyBinding()
  await binding.getByText(/该账号已绑定邮箱/).waitFor()
  assert.equal(signedIn, false)
  assert.equal(bindingCodeCalls(), beforeAlreadyBoundCode, '已绑定验证邮箱的账号不能发绑定码')
  assert.equal(await binding.getByLabel('新邮箱', { exact: true }).count(), 0)
  await closeLoginDialog()
  user = { ...fixture(), email: 'legacy@example.test' }; await openLogin()
  binding = await verifyBinding()
  await bindingAccountVerified(binding)
  assert.equal(await binding.getByLabel('当前密码', { exact: true }).count(), 0)
  await binding.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await page.screenshot({ path: join(artifacts, 'login-binding-legacy-unverified.png'), fullPage: true })
  await binding.getByRole('button', { name: '绑定并返回登录', exact: true }).click()
  await binding.waitFor({ state: 'detached' })
  await page.getByLabel('登录账号', { exact: true }).waitFor()
  assert.equal(user.email, 'bound@example.test'); assert.equal(user.email_verified, true)
  assert.equal(signedIn, false); await noBusinessSession()
  signedIn = false; user = fixture('teacher'); await openLogin()
  const beforeWrongRoleCode = bindingCodeCalls()
  binding = await verifyBinding()
  await binding.getByText('该账号为教师账号，请关闭弹窗并选择对应身份后重新验证', { exact: true }).waitFor()
  assert.equal(signedIn, false)
  assert.equal(bindingCodeCalls(), beforeWrongRoleCode, '身份不匹配先撤销会话，不发送绑定码')
  await closeLoginDialog()
  user = fixture(); await openLogin()
  console.log('PASS 登录页绑定：一次填写账号/密码/新邮箱，发码成功才显示验证码和绑定；验证码错误保留输入、历史未验证邮箱允许绑定、成功返回密码主卡不自动登录、已验证邮箱和错角色撤销')
  await loginAccount()
  // 身份选择不能改变服务端角色；错选身份必须撤销刚创建的会话后才允许重试。
  for (const method of ['password', 'email']) {
    signedIn = false; user = fixture('teacher', true); await openLogin()
    assert.equal(await page.getByRole('radio', { name: '学生', exact: true }).isChecked(), true)
    const logoutsBefore = calls.filter(call => call.path === '/api/auth/logout').length
    if (method === 'password') {
      await page.getByLabel('登录账号', { exact: true }).fill(user.account)
      await page.getByLabel('密码', { exact: true }).fill('Test-only-123')
    } else {
      await page.getByRole('button', { name: '邮箱登录', exact: true }).click()
      await page.getByLabel('邮箱', { exact: true }).fill(user.email)
      await page.getByRole('button', { name: '发送验证码', exact: true }).click()
      await page.getByLabel('邮箱验证码', { exact: true }).fill('123456')
    }
    await submitAuthentication()
    await page.getByText('该账号为教师账号，请选择对应身份后重新登录', { exact: true }).waitFor()
    assert.equal(signedIn, false)
    assert.equal(calls.filter(call => call.path === '/api/auth/logout').length, logoutsBefore + 1)
    assert.equal(await page.getByLabel('密码', { exact: true }).count() === 0 || await page.getByLabel('密码', { exact: true }).inputValue() === '', true)
    await loginAccount()
  }
  console.log('PASS 密码和邮箱登录错选身份均撤销新会话，选择真实身份后可重新登录')
  signedIn = false; user = fixture('student', true); await openLogin()
  await page.getByRole('button', { name: '邮箱登录', exact: true }).click()
  await page.getByLabel('邮箱', { exact: true }).fill('invalid')
  const sendCode = page.getByRole('button', { name: '发送验证码', exact: true })
  const codeCalls = () => calls.filter(call => call.path === '/api/auth/email-code').length
  const beforeInvalidEmail = codeCalls()
  await sendCode.click()
  await page.getByText('请输入正确的邮箱地址', { exact: true }).waitFor()
  assert.equal(codeCalls(), beforeInvalidEmail)
  await page.getByLabel('邮箱', { exact: true }).fill(user.email)
  await sendCode.click()
  await page.getByLabel('邮箱验证码', { exact: true }).fill('000000')
  await submitAuthentication()
  await page.getByText('验证码错误', { exact: true }).waitFor()
  assert.equal(signedIn, false)
  await page.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await submitAuthentication(); await workspace()
  assert.equal(cloudflareRequests, disabledCloudflareRequests, '关闭 Turnstile 时登录、重试和发码均不请求 Cloudflare')
  assert.equal(await page.locator('script[src*="challenges.cloudflare.com"]').count(), 0)
  console.log('PASS Turnstile=false 无站点键/Cloudflare 请求；空密码、错密码、错误邮箱和错验证码仍失败，正确凭据可登录')
  for (const invalid of ['false', 0, 1, null, {}, []]) {
    turnstileEnabled = invalid
    assert.equal(await page.evaluate(async () => {
      const { getAuthConfig } = await import('/src/api/session.ts')
      try { await getAuthConfig(); return false } catch { return true }
    }), true, 'turnstile_enabled 必须为 boolean')
  }
  for (const value of [undefined, true, false]) {
    turnstileEnabled = value
    assert.equal(await page.evaluate(async () => {
      const { getAuthConfig } = await import('/src/api/session.ts')
      return (await getAuthConfig()).turnstile_enabled
    }), value ?? true)
  }
  signedIn = false; authAvailable = false; await openLogin()
  await page.getByRole('alert').filter({ hasText: '认证配置不可用' }).waitFor()
  assert.equal(await submitLogin.isDisabled(), true, '关闭 Turnstile 不得放行 unavailable 认证配置')
  assert.equal(cloudflareRequests, disabledCloudflareRequests)
  authAvailable = true; turnstileEnabled = undefined
  console.log('PASS 开关严格 boolean 校验、缺省启用兼容；available=false 继续阻止密码登录')
  user = fixture(); await openLogin()
  await page.waitForFunction(() => Boolean(window.turnstile))
  assert.ok(cloudflareRequests > disabledCloudflareRequests, '缺省启用仍加载原 Turnstile 流程')
  await page.screenshot({ path: join(artifacts, 'login-desktop.png'), fullPage: true })
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: width === 375 ? 480 : 900 })
    await noHorizontalOverflow()
    await page.getByRole('button', { name: '邮箱登录', exact: true }).click()
    let email = await emailLoginDialog()
    await emailFieldsLayout(email, '邮箱')
    await page.screenshot({ path: join(artifacts, `login-email-${width}.png`), fullPage: true })
    binding = await openLoginBinding()
    await emailFieldsLayout(binding, '新邮箱', { codeVisible: false })
    await page.screenshot({ path: join(artifacts, `login-binding-before-${width}.png`), fullPage: true })
    if (width === 375) {
      for (const control of [binding.getByLabel('登录账号', { exact: true }),
        binding.getByLabel('当前密码', { exact: true }),
        binding.getByLabel('新邮箱', { exact: true }),
        binding.getByRole('button', { name: '发送验证码', exact: true }),
        binding.getByRole('button', { name: '返回邮箱登录', exact: true })]) await scrollReachable(control)
      await noHorizontalOverflow(binding)
    }
    binding = await verifyBinding('Test-only-123', binding)
    await bindingAccountVerified(binding)
    await emailFieldsLayout(binding, '新邮箱', { sendBeforeCode: true })
    if (width === 375) {
      for (const control of [binding.getByRole('status').filter({ hasText: `账号 ${user.account} 已验证` }),
        binding.getByLabel('新邮箱', { exact: true }),
        binding.getByLabel('邮箱验证码', { exact: true }),
        binding.getByRole('button', { name: /\d+ 秒后重发/ }),
        binding.getByRole('button', { name: '绑定并返回登录', exact: true }),
        binding.getByRole('button', { name: '返回邮箱登录', exact: true })]) await scrollReachable(control)
      await noHorizontalOverflow(binding)
    }
    await page.screenshot({ path: join(artifacts, `login-binding-${width}.png`), fullPage: true })
    await binding.getByRole('button', { name: '返回邮箱登录', exact: true }).click()
    await returnedToEmail()
    email = await emailLoginDialog()
    const passwordEntry = email.getByRole('button', { name: '返回密码登录', exact: true })
    await passwordEntry.scrollIntoViewIfNeeded()
    await passwordEntry.focus(); await page.keyboard.press('Enter')
    await email.waitFor({ state: 'detached' })
    await page.getByLabel('密码', { exact: true }).waitFor()
    await noHorizontalOverflow()
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  console.log('PASS 桌面/375px 邮箱登录与绑定无横向溢出、邮箱标签单行、表单纵向排列；375×480 绑定验证前后控件滚动可达；可通过键盘返回密码入口')
  const recoveryTrigger = page.getByRole('button', { name: '忘记密码？', exact: true })
  await recoveryTrigger.click()
  const recoveryDialog = page.getByRole('dialog', { name: '找回密码', exact: true })
  await recoveryDialog.waitFor()
  await recoveryDialog.getByRole('button', { name: /联系管理员/ }).waitFor()
  await recoveryDialog.getByRole('button', { name: /绑定.*邮箱.*重置/ }).waitFor()
  await page.screenshot({ path: join(artifacts, 'password-recovery-options.png'), fullPage: true })
  await recoveryDialog.getByRole('button', { name: /联系管理员/ }).click()
  assert.equal(await recoveryDialog.locator('a[href^="mailto:"]').count(), 0, '未配置管理员邮箱时不展示邮箱发件入口')
  await page.keyboard.press('Escape')
  await recoveryDialog.waitFor({ state: 'detached' })
  assert.equal(await recoveryTrigger.evaluate(element => document.activeElement === element), true, '弹窗关闭后焦点回到找回密码入口')
  await page.setViewportSize({ width: 375, height: 812 }); await page.emulateMedia({ reducedMotion: 'reduce' })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
  await page.screenshot({ path: join(artifacts, 'login-mobile.png'), fullPage: true })
  await page.setViewportSize({ width: 375, height: 480 })
  await page.getByRole('button', { name: '忘记密码？', exact: true }).click()
  await recoveryDialog.getByRole('button', { name: /绑定.*邮箱.*重置/ }).click()
  await page.getByLabel('确认新密码', { exact: true }).fill('Short-viewport-only-123')
  const resetSubmit = page.getByRole('button', { name: '重置密码', exact: true })
  await resetSubmit.scrollIntoViewIfNeeded()
  const resetBounds = await resetSubmit.boundingBox()
  assert.ok(resetBounds && resetBounds.y >= 0 && resetBounds.y + resetBounds.height <= 480, '短视口内可滚动到完整提交按钮')
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
  await page.screenshot({ path: join(artifacts, 'login-short-reset.png'), fullPage: true })
  await closeLoginDialog()
  await page.setViewportSize({ width: 1440, height: 900 })
  console.log('PASS 默认密码登录、两种认证方式、学生/教师手动选择、无注册；375px 无横向溢出、短视口重置表单提交可达')
  for (const role of ['student', 'teacher', 'admin']) {
    for (const verified of [false, true]) {
      user = fixture(role, verified); signedIn = false; await openLogin(); await loginAccount()
      const section = await security()
      await section.getByRole('button', { name: '保存学工号资料', exact: true }).waitFor()
      if (verified) await section.getByRole('button', { name: '解绑邮箱', exact: true }).waitFor()
      else await section.getByRole('button', { name: '绑定并重新登录', exact: true }).waitFor()
    }
    signedIn = false; await openLogin(); await loginEmail(); await security()
  }
  console.log('PASS 三角色均支持有/无邮箱账号密码登录、邮箱登录及安全区；管理员默认折叠')
  for (const role of ['teacher', 'admin']) {
    user = fixture(role); signedIn = false; await openLogin(); await loginAccount()
    if (role === 'admin') await page.screenshot({ path: join(artifacts, 'admin-security-collapsed.png'), fullPage: true })
    let own = await security(); const other = await peer()
    await own.getByLabel('绑定邮箱', { exact: true }).fill('bound@example.test')
    const ownBinding = own.locator('form').filter({ has: page.getByRole('button', { name: '绑定并重新登录', exact: true }) })
    assert.equal(await ownBinding.locator('input[type="password"]').count(), 0, '个人中心首次绑定不收集密码')
    await own.getByRole('button', { name: '发送验证码', exact: true }).click()
    await own.getByLabel('邮箱验证码', { exact: true }).fill('123456')
    if (role === 'admin') await page.screenshot({ path: join(artifacts, 'admin-security-expanded.png'), fullPage: true })
    await own.getByRole('button', { name: '绑定并重新登录', exact: true }).click(); await revoked(other, updatedNotice)
    await loginEmail(); own = await security()
    await own.getByLabel('当前密码', { exact: true }).last().fill('Test-only-123')
    page.once('dialog', dialog => dialog.accept())
    await own.getByRole('button', { name: '解绑邮箱', exact: true }).click(); await loginScreen()
    await page.locator('.auth-notice').filter({ hasText: '邮箱已解绑，所有设备已退出，请使用账号密码重新登录' }).waitFor()
  }
  console.log('PASS 教师/管理员首次绑定和解绑；管理员折叠区操作与跨标签退出')
  user = { ...fixture('admin'), email: 'legacy@example.test' }; signedIn = false
  await openLogin(); await loginAccount()
  const legacy = await security()
  await legacy.getByLabel('重新绑定邮箱', { exact: true }).waitFor()
  const legacyForm = legacy.locator('form').filter({ has: page.getByRole('button', { name: '绑定并重新登录', exact: true }) })
  assert.equal(await legacyForm.locator('input[type="password"]').count(), 0)
  assert.equal(await legacy.getByRole('button', { name: '开始换绑', exact: true }).count(), 0)
  await legacy.getByLabel('当前密码', { exact: true }).last().fill('Test-only-123')
  await page.screenshot({ path: join(artifacts, 'security-legacy-unverified.png'), fullPage: true })
  page.once('dialog', dialog => dialog.accept())
  await legacy.getByRole('button', { name: '解绑邮箱', exact: true }).click(); await loginScreen()
  assert.equal(user.email, null)
  console.log('PASS 历史未验证邮箱显示无密码重新绑定表单、不进入双码换绑；独立密码区仍可解绑')
  user = { ...fixture('teacher'), email: 'legacy@example.test' }; signedIn = false
  await openLogin(); await loginAccount()
  const legacyRebind = await security(); const legacyPeer = await peer()
  await legacyRebind.getByLabel('重新绑定邮箱', { exact: true }).fill('bound@example.test')
  await legacyRebind.getByRole('button', { name: '发送验证码', exact: true }).click()
  await legacyRebind.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await legacyRebind.getByRole('button', { name: '绑定并重新登录', exact: true }).click()
  await revoked(legacyPeer, updatedNotice)
  assert.equal(user.email, 'bound@example.test'); assert.equal(user.email_verified, true)
  console.log('PASS 个人中心历史未验证邮箱可用邮箱 proof 重新绑定，成功撤销全部标签会话')
  user = fixture(); signedIn = false; await openLogin(); await loginAccount()
  assert.equal(await page.evaluate(() => JSON.stringify(localStorage)), '{}')
  const beforeRetry = refreshes
  assert.equal(await page.evaluate(async () => {
    const { sessionFetch } = await import('/src/api/session.ts')
    return (await sessionFetch('/api/test/retry', { method: 'POST', body: '{}' })).status
  }), 200)
  assert.equal(refreshes, beforeRetry + 1)
  assert.equal(calls.filter(call => call.path === '/api/test/retry').length, 2)
  await page.reload(); await workspace()
  const parallelPeer = await peer(); await Promise.all([page.reload(), parallelPeer.reload()]); await Promise.all([workspace(), workspace(parallelPeer)])
  assert.equal(maximumRefresh, 1)
  let section = await security()
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: width === 375 ? 812 : 900 })
    await emailFieldsLayout(section, '绑定邮箱')
    const profileEmail = page.getByText('邮箱（可选）', { exact: true })
    assert.equal(await profileEmail.evaluate(element => {
      const range = document.createRange(); range.selectNodeContents(element)
      return new Set(Array.from(range.getClientRects()).map(rect => Math.round(rect.top))).size === 1
    }), true, '个人资料邮箱标签单行可读')
    const number = section.locator('form').filter({ has: page.getByRole('button', { name: '保存学工号资料', exact: true }) })
    const email = section.locator('form').filter({ has: page.getByRole('button', { name: '绑定并重新登录', exact: true }) })
    const passwordEntry = section.getByRole('button', { name: '修改密码', exact: true })
    const [numberBounds, emailBounds, passwordBounds] = await Promise.all([number.boundingBox(), email.boundingBox(), passwordEntry.boundingBox()])
    assert.ok(numberBounds && emailBounds && passwordBounds)
    assert.ok(emailBounds.y >= numberBounds.y + numberBounds.height, '邮箱设置在学工号资料下方')
    assert.ok(passwordBounds.y >= emailBounds.y + emailBounds.height, '修改密码归入账号安全末尾')
    await passwordEntry.scrollIntoViewIfNeeded()
    await passwordEntry.focus(); await page.keyboard.press('Enter')
    await page.getByLabel('新密码', { exact: true }).waitFor()
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await page.screenshot({ path: join(artifacts, `security-layout-${width}.png`), fullPage: true })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  console.log('PASS 桌面/375px 个人中心无横向溢出、邮箱标签单行；学工号/邮箱/修改密码纵向排列且密码弹窗可达')
  const numberForm = section.locator('form').filter({ has: page.getByRole('button', { name: '保存学工号资料', exact: true }) })
  await numberForm.getByLabel('学工号', { exact: true }).fill('00042')
  await numberForm.getByLabel('当前密码', { exact: true }).fill('Test-only-123')
  await numberForm.getByRole('button', { name: '保存学工号资料', exact: true }).click()
  await section.getByText('学工号资料已更新；学工号不用于登录', { exact: true }).waitFor()
  assert.equal(await numberForm.getByLabel('当前密码', { exact: true }).inputValue(), '')
  assert.equal(user.email, null); await workspace(parallelPeer)
  console.log('PASS 旧存储清理、访问令牌不持久化、过期只重放一次、双标签串行恢复；无邮箱独立维护学工号')
  await section.getByLabel('绑定邮箱', { exact: true }).fill('bound@example.test')
  const bindForm = section.locator('form').filter({ has: page.getByRole('button', { name: '绑定并重新登录', exact: true }) })
  assert.equal(await bindForm.locator('input[type="password"]').count(), 0)
  await bindForm.getByRole('button', { name: '发送验证码', exact: true }).click()
  await bindForm.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await bindForm.getByLabel('绑定邮箱', { exact: true }).fill('changed@example.test')
  assert.equal(await bindForm.getByLabel('邮箱验证码', { exact: true }).inputValue(), '')
  assert.equal(await bindForm.getByLabel('邮箱验证码', { exact: true }).isDisabled(), true)
  await bindForm.getByLabel('绑定邮箱', { exact: true }).fill('bound@example.test')
  await page.clock.fastForward(60000)
  await bindForm.getByRole('button', { name: /^(?:发送验证码|重新发送验证码)$/ }).click()
  await bindForm.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  rejectMutation = true
  await bindForm.getByLabel('邮箱验证码', { exact: true }).fill('000000')
  await bindForm.getByRole('button', { name: '绑定并重新登录', exact: true }).click()
  await section.getByText('验证码错误', { exact: true }).waitFor(); await workspace(parallelPeer)
  assert.equal(await bindForm.getByLabel('绑定邮箱', { exact: true }).inputValue(), 'bound@example.test')
  assert.equal(await bindForm.getByLabel('邮箱验证码', { exact: true }).inputValue(), '000000')
  assert.equal(signedIn, true)
  rejectMutation = false
  await bindForm.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await page.screenshot({ path: join(artifacts, 'security-bind.png'), fullPage: true })
  await bindForm.getByRole('button', { name: '绑定并重新登录', exact: true }).click(); await revoked(parallelPeer, updatedNotice)
  console.log('PASS 首次绑定携带认证且仅提交邮箱/challenge/code；验证码失败保留输入/会话、成功全部标签退出并显示提示')
  await loginEmail(); section = await security(); const changePeer = await peer()
  await section.getByLabel('新邮箱', { exact: true }).fill('new@example.test')
  const changeForm = section.locator('form').filter({ has: page.getByRole('button', { name: '开始换绑', exact: true }) })
  assert.equal(await changeForm.locator('input[type="password"]').count(), 0, '换绑表单与解绑密码区分开')
  assert.equal(await changeForm.getByRole('button', { name: '解绑邮箱', exact: true }).count(), 0)
  const changeCallsBeforeCancel = calls.filter(call => call.path === '/api/users/me/email' && call.method === 'PUT').length
  await section.getByRole('button', { name: '开始换绑', exact: true }).click()
  await section.getByRole('button', { name: '取消换绑', exact: true }).waitFor()
  assert.equal(await section.getByRole('button', { name: '解绑邮箱', exact: true }).count(), 0, '双码事务进行中不混入解绑操作')
  await section.getByRole('button', { name: '取消换绑', exact: true }).click()
  await section.getByRole('button', { name: '解绑邮箱', exact: true }).waitFor()
  assert.equal(calls.filter(call => call.path === '/api/users/me/email' && call.method === 'PUT').length, changeCallsBeforeCancel)
  await section.getByRole('button', { name: '开始换绑', exact: true }).click()
  await section.getByRole('button', { name: '发送验证码', exact: true }).first().click()
  await section.getByRole('button', { name: '发送验证码', exact: true }).click()
  await section.getByLabel('旧邮箱验证码', { exact: true }).fill('123456')
  await section.getByLabel('新邮箱验证码', { exact: true }).fill('654321')
  await page.screenshot({ path: join(artifacts, 'security-change.png'), fullPage: true })
  await section.getByRole('button', { name: '确认换绑并重新登录', exact: true }).click(); await revoked(changePeer, updatedNotice)
  console.log('PASS 双邮箱验证码、事务与收件人契约、换绑退出/提示')
  await loginAccount(); section = await security(); const unbindPeer = await peer()
  await section.getByLabel('当前密码', { exact: true }).last().fill('Test-only-123')
  const deletes = () => calls.filter(call => call.path === '/api/users/me/email' && call.method === 'DELETE').length
  const beforeCancel = deletes()
  page.once('dialog', dialog => dialog.dismiss())
  await section.getByRole('button', { name: '解绑邮箱', exact: true }).click()
  assert.equal(deletes(), beforeCancel); await workspace()
  await page.screenshot({ path: join(artifacts, 'security-bound.png'), fullPage: true })
  page.once('dialog', dialog => dialog.accept())
  await section.getByRole('button', { name: '解绑邮箱', exact: true }).click()
  await revoked(unbindPeer, '邮箱已解绑，所有设备已退出，请使用账号密码重新登录')
  assert.equal(deletes(), beforeCancel + 1)
  await loginAccount(); section = await security(); await section.getByLabel('绑定邮箱', { exact: true }).waitFor()
  console.log('PASS 解绑取消不请求、确认 DELETE 密码契约、全部会话撤销、无邮箱账号仍可密码登录')
  await page.getByRole('button', { name: '修改密码', exact: true }).click()
  await page.getByLabel('当前密码', { exact: true }).last().fill('Test-only-123')
  await page.getByLabel('新密码', { exact: true }).fill('Changed-only-123')
  await page.getByLabel('确认新密码', { exact: true }).fill('Changed-only-123')
  await page.getByRole('button', { name: '确认修改', exact: true }).click(); await loginScreen()
  user = fixture('student', true); await openLogin()
  await page.getByRole('button', { name: '忘记密码？', exact: true }).click()
  await page.getByRole('dialog', { name: '找回密码', exact: true }).getByRole('button', { name: /绑定.*邮箱.*重置/ }).click()
  await page.getByLabel('邮箱', { exact: true }).fill(user.email)
  await page.getByLabel('新密码', { exact: true }).fill('Reset-only-123')
  await page.getByLabel('确认新密码', { exact: true }).fill('Reset-only-123')
  await page.getByRole('button', { name: '发送验证码', exact: true }).click()
  await page.getByLabel('邮箱验证码', { exact: true }).fill('000000')
  await page.getByRole('button', { name: '重置密码', exact: true }).click()
  await page.getByText('验证码错误', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('新密码', { exact: true }).inputValue(), 'Reset-only-123')
  assert.equal(await page.getByLabel('确认新密码', { exact: true }).inputValue(), 'Reset-only-123')
  rejectReset = false; await page.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await page.getByRole('button', { name: '重置密码', exact: true }).click()
  await page.getByText('密码已重置，所有设备已下线，请使用新密码登录', { exact: true }).waitFor()
  await page.getByLabel('登录账号', { exact: true }).waitFor()
  console.log('PASS 修改密码退出、重置错码保留两次密码、成功返回密码入口')
  devEnabled = true; await openLogin()
  for (const role of ['student', 'teacher']) {
    const before = calls.filter(call => call.path === '/api/auth/login/account').length
    await page.getByRole('button', { name: '填充' + (role === 'student' ? '学生' : '教师') + '开发账号', exact: true }).click()
    await page.getByText('已填充开发账号，请完成人机验证后手动登录', { exact: true }).waitFor()
    assert.equal(calls.filter(call => call.path === '/api/auth/login/account').length, before)
    assert.equal(await page.getByLabel('登录账号', { exact: true }).inputValue(), 'fake-' + role)
    await page.locator('.login-cta[type="submit"]').click(); await workspace()
    signedIn = false; await openLogin()
  }
  assert.equal(accountRequests, 2)
  turnstileEnabled = true; await openLogin(); await loginAccount()
  assert.ok(calls.some(call => call.path === '/api/auth/login/account' && call.body.turnstile_token === 'test-turnstile'))
  console.log('PASS 显式 Turnstile=true 仍携带验证票据完成密码登录')
  assert.equal(calls.some(call => ['/api/auth/register', '/api/auth/login/password'].includes(call.path)), false)
  assert.deepEqual(unexpected, []); assert.deepEqual(errors, [])
  console.log('PASS 开发账号返回 account 且仅填充；无已删除接口、意外外网或浏览器异常')
  console.log('Browser authentication checks complete; refresh requests:', refreshes, '; screenshots:', artifacts)
} catch (error) {
  console.error('Browser regression failed:', error)
  try {
    await page.screenshot({ path: join(artifacts, 'failure.png'), fullPage: true, timeout: 10000 })
    console.error('Failure screenshot:', join(artifacts, 'failure.png'))
  } catch (captureError) { console.error('Failure screenshot unavailable:', captureError.message) }
  console.error('Unexpected requests:', unexpected, '; browser errors:', errors)
  console.error('Recent fake API calls:', calls.slice(-18).map(call => call.method + ' ' + call.path))
  console.error('Web Locks:', await page.evaluate(() => navigator.locks.query()))
  throw error
} finally { await browser.close() }
