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
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
let user = fixture(), signedIn = false, devEnabled = false, rejectReset = true, rejectMutation = false
let turnstileEnabled, authAvailable = true, cloudflareRequests = 0
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
    if (bodyIn.purpose.startsWith('email_change')) {
      assert.equal(bodyIn.change_id, 'change-test')
      assert.equal(bodyIn.email, bodyIn.purpose === 'email_change_old' ? user.email : 'new@example.test')
    }
    status = 202; body = { challenge_id: 'challenge-' + bodyIn.purpose, expires_in: 300, retry_after: 60 }
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
    assert.deepEqual(bodyIn, { email: 'bound@example.test', current_password: 'Test-only-123', challenge_id: 'challenge-email_bind', code: '123456' })
    if (rejectMutation) { status = 400; body = { detail: { code: 'PASSWORD_INVALID', message: '当前密码错误' } } }
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
    authenticated(); assert.equal(request.headers()['x-csrf-token'], 'test-csrf'); signedIn = false; status = 204
  } else if (path === '/api/auth/me') { authenticated(); body = { user } }
  else if (path === '/api/admin/overview') body = { accounts: { admin_active: 1 }, resources: {}, task_status_counts: {}, tasks: [], task_total: 0, recent_task_limit: 50, admin_contact: '测试管理员' }
  else if (path === '/api/admin/accounts') body = []
  else if (path.includes('model-settings')) body = { mineru_limits: {}, embedding_model: 'test', rerank_model: 'test' }
  else if (path === '/api/generate/batches/latest') body = null
  else if (path === '/api/urges') body = { unread_count: 0, items: [] }
  else if (['/api/banks', '/api/spaces', '/api/papers', '/api/favorites', '/api/favorite-groups'].includes(path)) body = []
  else { unexpected.push(method + ' ' + path); status = 404; body = { detail: 'unexpected fake route' } }
  await route.fulfill({ status, contentType: 'application/json', ...(status === 204 ? {} : { body: JSON.stringify(body) }) })
})
const page = await context.newPage()
context.on('page', next => next.on('pageerror', error => errors.push(error.message)))
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(30000)
page.setDefaultNavigationTimeout(60000)
async function loginScreen(target = page) {
  await target.getByRole('button', { name: '密码登录', exact: true }).waitFor()
  assert.equal(await target.getByRole('button', { name: /注册|学工号登录|开通账号登录/ }).count(), 0)
  assert.equal(await target.getByRole('radio').count(), 0)
  assert.deepEqual(await target.getByRole('navigation', { name: '认证方式' }).getByRole('button').allTextContents(), ['密码登录', '邮箱登录'])
}
async function openLogin() {
  await page.goto(origin); await loginScreen()
  assert.equal(await page.getByRole('button', { name: '密码登录', exact: true }).getAttribute('aria-pressed'), 'true')
  await page.getByLabel('登录账号', { exact: true }).waitFor()
}
async function workspace(target = page) {
  if (user.role === 'admin') await target.getByRole('heading', { name: '管理员面板', exact: true }).waitFor()
  else await target.getByRole('button', { name: '个人中心', exact: true }).waitFor()
}
async function loginAccount() {
  await page.getByRole('button', { name: '密码登录', exact: true }).click()
  await page.getByLabel('登录账号', { exact: true }).fill(user.account)
  await page.getByLabel('密码', { exact: true }).fill('Test-only-123')
  await page.getByRole('button', { name: '登录并进入工作台', exact: true }).click(); await workspace()
}
async function loginEmail() {
  await page.getByRole('button', { name: '邮箱登录', exact: true }).click()
  await page.getByLabel('邮箱', { exact: true }).fill(user.email)
  await page.getByRole('button', { name: '发送验证码', exact: true }).click()
  await page.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await page.getByRole('button', { name: '登录并进入工作台', exact: true }).click(); await workspace()
}
async function security() {
  if (user.role === 'admin') {
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
  await loginScreen(); await page.getByText(notice, { exact: true }).waitFor()
  await loginScreen(next); await next.reload(); await loginScreen(next); await next.close()
  assert.equal(await page.evaluate(() => localStorage.getItem('mathcraft-auth')), null)
}
const updatedNotice = '邮箱已更新，所有设备已退出，请使用账号密码重新登录'
try {
  turnstileEnabled = false
  await openLogin()
  const disabledCloudflareRequests = cloudflareRequests
  assert.equal(disabledCloudflareRequests, 0)
  const submitLogin = page.getByRole('button', { name: '登录并进入工作台', exact: true })
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
  await loginAccount()
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
  await submitLogin.click()
  await page.getByText('验证码错误', { exact: true }).waitFor()
  assert.equal(signedIn, false)
  await page.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await submitLogin.click(); await workspace()
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
  await openLogin()
  await page.waitForFunction(() => Boolean(window.turnstile))
  assert.ok(cloudflareRequests > disabledCloudflareRequests, '缺省启用仍加载原 Turnstile 流程')
  await page.screenshot({ path: join(artifacts, 'login-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 375, height: 812 }); await page.emulateMedia({ reducedMotion: 'reduce' })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
  await page.screenshot({ path: join(artifacts, 'login-mobile.png'), fullPage: true })
  await page.setViewportSize({ width: 1440, height: 900 })
  console.log('PASS 默认密码登录、仅两个入口、无注册/角色；375px 无横向溢出')
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
    await own.getByLabel('当前密码', { exact: true }).last().fill('Test-only-123')
    await own.getByRole('button', { name: '发送验证码', exact: true }).click()
    await own.getByLabel('邮箱验证码', { exact: true }).fill('123456')
    if (role === 'admin') await page.screenshot({ path: join(artifacts, 'admin-security-expanded.png'), fullPage: true })
    await own.getByRole('button', { name: '绑定并重新登录', exact: true }).click(); await revoked(other, updatedNotice)
    await loginEmail(); own = await security()
    await own.getByLabel('当前密码', { exact: true }).last().fill('Test-only-123')
    page.once('dialog', dialog => dialog.accept())
    await own.getByRole('button', { name: '解绑邮箱', exact: true }).click(); await loginScreen()
    await page.getByText('邮箱已解绑，所有设备已退出，请使用账号密码重新登录', { exact: true }).waitFor()
  }
  console.log('PASS 教师/管理员首次绑定和解绑；管理员折叠区操作与跨标签退出')
  user = { ...fixture('admin'), email: 'legacy@example.test' }; signedIn = false
  await openLogin(); await loginAccount()
  const legacy = await security()
  await legacy.getByLabel('重新验证邮箱', { exact: true }).waitFor()
  assert.equal(await legacy.getByRole('button', { name: '开始换绑', exact: true }).count(), 0)
  await legacy.getByLabel('当前密码', { exact: true }).last().fill('Test-only-123')
  await page.screenshot({ path: join(artifacts, 'security-legacy-unverified.png'), fullPage: true })
  page.once('dialog', dialog => dialog.accept())
  await legacy.getByRole('button', { name: '解绑邮箱', exact: true }).click(); await loginScreen()
  assert.equal(user.email, null)
  console.log('PASS 历史未验证邮箱不进入双码换绑；可使用绑定表单当前密码解绑')
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
  await bindForm.getByLabel('当前密码', { exact: true }).fill('Test-only-123')
  await bindForm.getByRole('button', { name: '发送验证码', exact: true }).click()
  await bindForm.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await bindForm.getByLabel('绑定邮箱', { exact: true }).fill('changed@example.test')
  assert.equal(await bindForm.getByLabel('邮箱验证码', { exact: true }).inputValue(), '')
  assert.equal(await bindForm.getByLabel('邮箱验证码', { exact: true }).isDisabled(), true)
  await bindForm.getByLabel('绑定邮箱', { exact: true }).fill('bound@example.test')
  await bindForm.getByRole('button', { name: '发送验证码', exact: true }).click()
  await bindForm.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  rejectMutation = true
  await bindForm.getByRole('button', { name: '绑定并重新登录', exact: true }).click()
  await section.getByText('当前密码错误', { exact: true }).waitFor(); await workspace(parallelPeer)
  assert.equal(await bindForm.getByLabel('绑定邮箱', { exact: true }).inputValue(), 'bound@example.test')
  assert.equal(await bindForm.getByLabel('当前密码', { exact: true }).inputValue(), 'Test-only-123')
  rejectMutation = false
  await page.screenshot({ path: join(artifacts, 'security-bind.png'), fullPage: true })
  await bindForm.getByRole('button', { name: '绑定并重新登录', exact: true }).click(); await revoked(parallelPeer, updatedNotice)
  console.log('PASS 首次绑定携带认证与当前密码、失败保留输入/会话、成功全部标签退出并显示提示')
  await loginEmail(); section = await security(); const changePeer = await peer()
  await section.getByLabel('新邮箱', { exact: true }).fill('new@example.test')
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
    await page.getByRole('button', { name: '登录并进入工作台', exact: true }).click(); await workspace()
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
