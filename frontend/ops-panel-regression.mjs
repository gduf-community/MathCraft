/* global AbortController, URL, console, document, process, structuredClone, window, getComputedStyle */
/** 真实应用与浏览器回归；所有 API 为合成响应，不启动后端或访问模型。 */
import assert from 'node:assert/strict'
import { mkdir, readFile, readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer, preview } from 'vite'

const require = createRequire(join(tmpdir(), 'mathcraft-auth-browser', 'package.json'))
const { chromium } = require('playwright-core')
const root = fileURLToPath(new URL('.', import.meta.url))
const output = fileURLToPath(new URL('../output/playwright/ops/', import.meta.url))
const server = await createServer({ root, configFile: join(root, 'vite.auth-test.config.mjs'),
  server: { port: 5182, strictPort: true, hmr: false }, logLevel: 'error' })
await server.listen()
const origin = 'http://127.0.0.1:5182'
const allowedOrigins = new Set([origin])
const browser = await chromium.launch({ executablePath: process.env.AUTH_BROWSER ?? join(
  homedir(), 'AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe',
), headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
await page.clock.install()
const errors = [], unexpected = [], calls = [], requests = [], overrides = [], gates = []
const user = { id: 'ops-test-admin', account: 'fake-ops-admin', role: 'admin', identity: '管理员',
  display_name: '合成运维管理员', email_verified: false, password_change_recommended: false }
const legacy = { accounts: { admin_active: 1, teacher_active: 2 }, resources: { banks: 3, documents: 8, papers: 2 },
  admin_contact: '', task_total: 51, task_scope: 'persisted_generation_batches',
  task_status_counts: { completed: 51 }, tasks: [] }
let signedIn = false, realData = null, realFailure = 404, legacyFailure = false
let delayed = null, readPayload = undefined
page.on('pageerror', error => errors.push(error.message))
await context.addInitScript(() => {
  window.__opsOpened = []
  window.open = (...args) => { window.__opsOpened.push(args); return null }
})

// 单次可控响应在请求进入时固定快照，显式放行；不靠后端或长延迟制造竞态。
function nextResponse(path, method, body, { status = 200, hold = false, query } = {}) {
  let arrive, release, finish
  const entered = new Promise(resolve => { arrive = resolve })
  const gate = new Promise(resolve => { release = resolve })
  const done = new Promise(resolve => { finish = resolve })
  const override = { path, method, query, body: structuredClone(body), status, entered, done,
    arrive, finish, gate, release, hold }
  overrides.push(override)
  gates.push(override)
  return override
}

async function renderSettled() {
  await page.evaluate(() => new Promise(resolve => {
    const channel = new window.MessageChannel()
    channel.port1.onmessage = () => { channel.port1.close(); channel.port2.close(); resolve() }
    channel.port2.postMessage(null)
  }))
}

async function visibility(hidden) {
  await page.evaluate(value => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => value })
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => value ? 'hidden' : 'visible' })
    document.dispatchEvent(new window.Event('visibilitychange'))
  }, hidden)
}

async function pauseClockAt(milliseconds) {
  await page.clock.pauseAt(new Date(milliseconds))
}

async function freezeClock() {
  await pauseClockAt(await page.evaluate(() => Date.now() + 100))
}

async function checkNoTraceSideEffects(action) {
  await freezeClock()
  try {
    const beforeRequests = requests.length
    const beforePages = context.pages().length
    const beforeOpens = await page.evaluate(() => window.__opsOpened.length)
    await action()
    await renderSettled()
    assert.equal(await page.evaluate(() => window.__opsOpened.length), beforeOpens, '正文检查不得调用 window.open')
    assert.equal(context.pages().length, beforePages, '正文检查不得创建标签页')
    const added = requests.slice(beforeRequests)
    assert.deepEqual(added.filter(request => request.path.startsWith('/api/')
      || /phoenix|\/traces?(?:\/|$)|trace[-_/]access|audit/.test(request.path)), [],
    '正文检查不得发出任何 API、Phoenix、trace 或审计请求')
  } finally { await page.clock.resume() }
}

await context.route('**/*', async route => {
  const req = route.request(), url = new URL(req.url()), path = url.pathname
  if (!allowedOrigins.has(url.origin)) {
    unexpected.push(url.origin + path)
    return route.abort()
  }
  requests.push({ path, method: req.method(), query: url.search })
  if (!path.startsWith('/api/')) return route.continue()
  calls.push({ path, method: req.method(), query: url.search })
  const index = overrides.findIndex(item => item.path === path && item.method === req.method()
    && (item.query === undefined || item.query(url.searchParams)))
  if (index !== -1) {
    const item = overrides.splice(index, 1)[0]
    item.arrive()
    try {
      if (item.hold) await item.gate
      await route.fulfill({ status: item.status, contentType: 'application/json', body: JSON.stringify(item.body) })
    } finally { item.finish() }
    return
  }
  let status = 200, body
  const login = () => ({ access_token: 'fake-ops-test-access', token_type: 'bearer', expires_in: 900, user })
  if (path === '/api/auth/config') body = { site_key: '', csrf_token: 'fake-ops-test-csrf',
    turnstile_enabled: false, available: true, methods: ['account_password'] }
  else if (path === '/api/auth/refresh') {
    status = signedIn ? 200 : 401
    body = signedIn ? login() : { detail: { code: 'TOKEN_EXPIRED', message: '请登录' } }
  } else if (path === '/api/auth/login/account') { signedIn = true; body = login() }
  else if (path === '/api/auth/me' || path === '/api/users/me') body = user
  else if (path === '/api/admin/overview') {
    status = legacyFailure ? 503 : 200
    body = legacyFailure ? { detail: { code: 'SYNTHETIC_UNAVAILABLE', message: '合成平台统计故障' } } : legacy
  } else if (path === '/api/admin/accounts') body = [{ id: 'fake-teacher', account: 'fake-teacher',
    display_name: '合成教师', role: 'teacher', identity: '教师', status: 'active', created_at: new Date().toISOString() }]
  else if (path === '/api/admin/rag-settings') body = { active: {
    embedding_model: 'fake-embedding', embedding_base_url: 'https://example.test/v1',
    embedding_key_configured: false, embedding_key_masked: null, rerank_model: 'fake-reranker',
    rerank_base_url: 'https://example.test/v1', rerank_key_configured: false, rerank_key_masked: null,
  }, pending: null, vector_store: { backend: 'chroma', path: 'synthetic-vectors', available: true, message: '' },
  rebuild: { status: 'idle', progress: 0, stage: '', error: null }, revision: 1 }
  else if (path === '/api/notifications') body = realData?.notifications ?? { unread_count: 0, items: [] }
  else if (path === '/api/notifications/read') {
    readPayload = req.postDataJSON()
    const ids = readPayload.ids
    const items = realData.notifications.items.map(item => ids === null || ids.includes(item.id)
      ? { ...item, read: true } : item)
    realData.notifications = { items, unread_count: ids === null ? 0 : items.filter(item => !item.read).length }
    body = { ok: true }
  }
  else if (path.startsWith('/api/notifications/') && req.method() === 'DELETE') {
    const id = decodeURIComponent(path.slice('/api/notifications/'.length))
    const items = realData.notifications.items.filter(item => item.id !== id)
    realData.notifications = { items, unread_count: items.filter(item => !item.read).length }
    body = { ok: true }
  }
  else if (path.startsWith('/api/admin/ops/')) {
    if (delayed && path.endsWith('/runs') && url.searchParams.get('owner_user_id') === delayed.owner) {
      await delayed.promise
    }
    if (realFailure) {
      status = realFailure
      body = { detail: { code: status === 503 ? 'OPS_DATA_UNAVAILABLE' : 'NOT_FOUND',
        message: status === 503 ? '运维摘要暂不可用' : 'Not Found' } }
    } else if (path.endsWith('/overview')) body = realData.overview
    else if (path.endsWith('/runs')) {
      body = realData.runs
      const owner = url.searchParams.get('owner_user_id')
      if (owner === 'old-user' || owner === 'new-user') body = { ...realData.runs,
        items: [{ ...realData.runs.items[0], run_id: owner === 'old-user' ? 'stale-run' : 'fresh-run' }],
        page: { ...realData.runs.page, has_more: false, next_cursor: null } }
    }
    else if (path.endsWith('/dependencies')) body = realData.dependencies
    else if (path.endsWith('/alerts')) body = realData.alerts
    else body = realData.detail
  } else {
    unexpected.push(req.method() + ' ' + path)
    status = 404; body = { detail: { code: 'UNEXPECTED_TEST_REQUEST', message: '合成测试未定义此接口' } }
  }
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
})

const nav = name => page.getByRole('navigation', { name: '管理员后台导航' })
  .getByRole('button', { name, exact: true })
const card = (scope, title) => scope.getByRole('heading', { name: title, exact: true }).locator('xpath=ancestor::section[1]')
const fact = (scope, label) => scope.getByText(label, { exact: true }).locator('..').locator('dd')
async function setDemo(enabled) {
  const checkbox = page.getByLabel('使用演示数据')
  if (await checkbox.isChecked() !== enabled) await checkbox.click()
  await page.waitForFunction(value => document.querySelector('section[aria-label="运维演示设置"] input[type="checkbox"]')?.checked === value, enabled)
}
let passed = 0
async function check(name, action) {
  await action()
  passed++
  console.log('PASS ' + name)
}

try {
  await mkdir(output, { recursive: true })
  await page.goto(origin)
  await page.getByLabel('登录账号', { exact: true }).fill('fake-ops-admin')
  await page.getByLabel('密码', { exact: true }).fill('Fake-test-password')
  await page.getByRole('button', { name: '进入学习空间', exact: true }).click()
  await page.getByRole('heading', { name: '运维后台', exact: true }).waitFor()

  await check('登录门禁、七个入口与真实接口未就绪', async () => {
    assert.equal(await page.getByRole('navigation', { name: '管理员后台导航' }).getByRole('button').count(), 7)
    assert.equal(await page.getByLabel('使用演示数据').isChecked(), false)
    await page.getByText('持久化生成批次总数：51', { exact: true }).waitFor()
    await page.getByRole('alert').filter({ hasText: /尚未|未就绪|未实现/ }).waitFor()
  })

  // 从真实演示适配器取得完整契约夹具，用来测试真实 API 校验与错误边界。
  realData = await page.evaluate(async () => {
    const { createDemoOpsClient } = await import('/src/api/adminOpsDemo.ts')
    const client = createDemoOpsClient('normal'), signal = new AbortController().signal
    const runs = await client.listRuns({}, signal)
    return { overview: await client.getOverview({}, signal), runs,
      detail: await client.getRun(runs.items[0].run_id, signal),
      dependencies: await client.listDependencies({}, signal), alerts: await client.listAlerts({}, signal),
      notifications: await client.listNotifications(signal) }
  })

  await check('演示筛选、分页去重与抽屉焦点归还', async () => {
    await setDemo(true)
    await nav('出题运行').click()
    const rows = page.getByRole('button', { name: /^查看运行 / })
    await rows.first().waitFor()
    assert.equal(await rows.count(), 20)
    await page.getByRole('button', { name: '加载更多', exact: true }).click()
    await page.getByText(/已追加分页，自动刷新暂停/).waitFor()
    assert.ok(await rows.count() > 20)
    const names = await rows.evaluateAll(elements => elements.map(element => element.getAttribute('aria-label')))
    assert.equal(new Set(names).size, names.length)
    await page.getByRole('button', { name: '刷新第一页', exact: true }).click()
    await page.getByText(/首屏每 15 秒自动刷新/).waitFor()
    assert.equal(await rows.count(), 20)
    await page.getByRole('combobox', { name: '交付质量', exact: true }).selectOption('attention')
    assert.equal(await rows.count(), 20, '未应用的筛选不能发请求')
    await page.getByRole('button', { name: '应用筛选', exact: true }).click()
    await page.waitForFunction(() => document.querySelectorAll('[aria-label^="查看运行 "]').length < 20)
    const opener = rows.first()
    const name = await opener.getAttribute('aria-label')
    await opener.click()
    const drawer = page.getByRole('dialog')
    await drawer.waitFor()
    await drawer.getByText(/最终版本|审核覆盖/).first().waitFor()
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press('Tab')
      assert.equal(await drawer.evaluate(element => element.contains(document.activeElement)), true)
    }
    await page.keyboard.press('Escape')
    await drawer.waitFor({ state: 'hidden' })
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), name)
    assert.equal(await page.getByRole('combobox', { name: '交付质量', exact: true }).inputValue(), 'attention')
    await page.getByRole('button', { name: '重置查询', exact: true }).click()
    await rows.nth(19).waitFor()
  })

  await check('演示通知读删不写真实接口，旧轮次跨默认窗口可定位', async () => {
    const before = calls.filter(call => call.path.startsWith('/api/notifications') && call.method !== 'GET').length
    await page.getByRole('button', { name: '管理员通知', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '管理员通知', exact: true })
    await dialog.getByRole('button', { name: '标记全部已读', exact: true }).click()
    await page.getByRole('status').filter({ hasText: '全部通知已标记为已读' }).first().waitFor()
    const old = realData.notifications.items.find(item => Date.parse(item.created_at) < Date.now() - 86400000)
    assert.ok(old, '演示必须有超过24小时的通知')
    const item = dialog.getByRole('listitem').filter({ hasText: old.title })
    await item.getByRole('button', { name: '查看异常轮次', exact: true }).click()
    await page.getByText(/正按告警 ID 定位整个保留期/).waitFor()
    assert.equal(await page.getByLabel('告警 ID（通知精确定位）').inputValue(), old.ops_alert_id)
    await page.getByText(old.ops_alert_id, { exact: true }).waitFor()
    await page.getByRole('combobox', { name: '时间窗口', exact: true }).selectOption('24h')
    await page.getByRole('button', { name: '应用筛选', exact: true }).click()
    await page.getByText(/当前筛选下没有匹配记录/).waitFor()
    await page.getByRole('button', { name: '管理员通知', exact: true }).click()
    await dialog.getByRole('button', { name: /^删除通知：/ }).first().click()
    await page.getByRole('status').filter({ hasText: '通知已删除' }).first().waitFor()
    await page.keyboard.press('Escape')
    assert.equal(calls.filter(call => call.path.startsWith('/api/notifications') && call.method !== 'GET').length, before)
  })

  await check('部分可用、空集、服务故障及迟到演示请求隔离', async () => {
    await page.getByLabel('演示场景').selectOption('partial')
    await nav('出题运行').click()
    await page.getByText(/摘要存在采集缺口/).waitFor()
    await page.getByLabel('演示场景').selectOption('empty')
    await page.getByText(/当前筛选下没有匹配记录/).waitFor()
    await page.getByLabel('演示场景').selectOption('error')
    await page.getByRole('alert').filter({ hasText: /暂不可用/ }).waitFor()
    await page.getByLabel('演示场景').selectOption('loading')
    await page.getByRole('status').filter({ hasText: /正在加载运维摘要/ }).waitFor()
    await setDemo(false)
    await page.getByRole('alert').filter({ hasText: /接口尚未就绪/ }).waitFor()
    await page.waitForTimeout(2200)
    assert.equal(await page.getByRole('button', { name: /^查看运行 / }).count(), 0)
  })

  await check('真实适配器契约、未知保留与安全追踪路径', async () => {
    realFailure = 0
    await page.getByRole('button', { name: '重新加载第一页', exact: true }).click()
    await page.getByRole('button', { name: /^查看运行 / }).first().waitFor()
    const result = await page.evaluate(async data => {
      const api = await import('/src/api/adminOps.ts')
      const rejects = operation => { try { operation(); return false } catch { return true } }
      const unknown = structuredClone(data.runs.items[0])
      unknown.collection_state = 'partial'
      unknown.unknown_fields = ['counts.actual_count', 'review', 'quality', 'degradation']
      unknown.counts.actual_count = null
      unknown.counts.quantity_status = 'unknown'
      unknown.quality = { status: 'unknown', reason_codes: null }
      unknown.degradation = { occurred: null, reason_codes: null }
      unknown.review = { required: null, eligible_count: null, covered_count: null, passed_count: null,
        skipped_count: null, unknown_count: null, coverage_rate: null, coverage_reason: 'not_collected', status: 'unknown' }
      const parsed = api.parseOpsRun(unknown)
      const expired = structuredClone(data.runs.items[0])
      expired.trace.expires_at = new Date(Date.now() - 1000).toISOString()
      const invalidRates = [
        { numerator: null, denominator: null, value: 1, excluded_unknown: null, reason: 'not_collected' },
        { numerator: 0, denominator: null, value: 0, excluded_unknown: null, reason: 'incomplete' },
        { numerator: null, denominator: 0, value: 1, excluded_unknown: null, reason: 'no_samples' },
        { numerator: 1, denominator: 2, value: 1, excluded_unknown: 0, reason: null },
      ]
      const invalidReviews = [
        { required: false, eligible_count: 0, covered_count: 0, passed_count: 0, skipped_count: 0,
          unknown_count: 0, coverage_rate: 1, coverage_reason: 'not_required', status: 'not_required' },
        { ...unknown.review, coverage_rate: 1 },
        { ...data.runs.items[0].review, coverage_rate: 0 },
      ]
      const notice = data.notifications.items.find(item => item.kind.startsWith('ops_'))
      const unlinked = { ...notice }
      delete unlinked.ops_alert_id
      delete unlinked.ops_episode_no
      return { unknownCount: parsed.counts.actual_count, quality: parsed.quality.status,
        expiredSummaryPreserved: api.parseOpsRun(expired).run_id === expired.run_id,
        invalidRates: invalidRates.map(rate => rejects(() => api.parseOpsOverview({ ...data.overview,
          execution: { ...data.overview.execution, completion_rate: rate } }))),
        validPartialRate: api.parseOpsOverview({ ...data.overview, execution: { ...data.overview.execution,
          completion_rate: { numerator: 1, denominator: 2, value: 0.5, excluded_unknown: 3, reason: 'incomplete' } } })
          .execution.completion_rate.value,
        invalidReviews: invalidReviews.map(review => rejects(() => api.parseOpsRun({ ...data.runs.items[0], review }))),
        invalidNotifications: ['ops_alert_trigger', 'ops_alert_reminder', 'ops_alert_recovery'].flatMap(kind =>
          [unlinked, { ...unlinked, ops_alert_id: notice.ops_alert_id }, { ...unlinked, ops_episode_no: 1 }]
            .map(item => rejects(() => api.parseOpsNotifications({ unread_count: 1, items: [{ ...item, kind }] })))),
        legacyNotificationCompatible: api.parseOpsNotifications({ unread_count: 0,
          items: [{ ...unlinked, kind: 'bank_ready', read: true }] }).items[0].ops_alert_id === null,
        invalidEnum: rejects(() => api.parseOpsRun({ ...data.runs.items[0], execution_status: 'fabricated' })),
        invalidNumber: rejects(() => api.parseOpsRun({ ...data.runs.items[0], counts: { ...data.runs.items[0].counts, actual_count: -1 } })),
        unsafe: ['https://example.test', '//example.test', '/%2fexample.test', '/%252fexample.test',
          '/trace?token=fake', '/trace?access_token=fake', '/a/../trace', '/trace#access', '/trace\\evil']
          .map(path => api.isSafeOpsTracePath(path)),
        safe: api.isSafeOpsTracePath('/phoenix/projects/test/traces/demo'),
      }
    }, realData)
    assert.equal(result.unknownCount, null)
    assert.equal(result.quality, 'unknown')
    assert.equal(result.expiredSummaryPreserved, true)
    assert.ok(result.invalidRates.every(Boolean))
    assert.equal(result.validPartialRate, 0.5)
    assert.ok(result.invalidReviews.every(Boolean))
    assert.ok(result.invalidNotifications.every(Boolean))
    assert.equal(result.legacyNotificationCompatible, true)
    assert.equal(result.invalidEnum, true)
    assert.equal(result.invalidNumber, true)
    assert.ok(result.unsafe.every(value => value === false))
    assert.equal(result.safe, true)
  })

  await check('v1 扩展兼容、逐字段拒绝非法证据与未来规则保留原标识', async () => {
    const results = await page.evaluate(async data => {
      const api = await import('/src/api/adminOps.ts')
      const checks = []
      const accepts = (name, action, verify = () => true) => {
        try { checks.push({ name, ok: verify(action()) }) }
        catch (error) { checks.push({ name, ok: false, error: String(error) }) }
      }
      const rejects = (name, action) => {
        try { action(); checks.push({ name, ok: false }) }
        catch (error) { checks.push({ name, ok: error.code === 'INVALID_OPS_RESPONSE', code: error.code }) }
      }
      const config = { warning: 3, critical: 7, unit: 'attempts', window_seconds: 300, source: 'synthetic_config' }
      const unknownConfig = { warning: null, critical: null, unit: null, window_seconds: null, source: null }
      const metric = { metric_id: 'ingestion_delay', status: 'healthy', value: 12, unit: 'ms',
        observed_at: new Date().toISOString(), fresh_until: new Date(Date.now() + 60000).toISOString(),
        unknown_reason: null, effective_config: config }
      const monitoring = { metrics: [metric], regeneration_config: config }
      const versions = { final_content_revision: 'final-r2',
        final_questions: [{ question_id: 'q1', content_revision: 'q1-r2' }, { question_id: 'q2', content_revision: 'q2-r3' }],
        required_scopes: ['difficulty', 'correctness'], evidence: [
          { question_id: 'q1', content_revision: 'q1-r1', scope: 'correctness', status: 'passed' },
          { question_id: 'q1', content_revision: 'q1-r2', scope: 'difficulty', status: 'passed' },
        ] }
      const guidance = { impact: '合成影响说明', owner_module: 'synthetic_owner', manual_action_required: true,
        next_step: '合成排查步骤' }
      const overview = { ...data.overview, self_monitoring: monitoring }
      const detail = { ...data.detail, review_versions: versions, regeneration_config: config }
      const alert = { ...data.alerts.items[0], guidance, effective_config: config }
      for (const [name, value, parse, fields] of [
        ['overview', overview, api.parseOpsOverview, ['self_monitoring']],
        ['detail', detail, api.parseOpsRunDetail, ['review_versions', 'regeneration_config']],
        ['alert', alert, api.parseOpsAlert, ['guidance', 'effective_config']],
      ]) {
        const old = structuredClone(value)
        for (const field of fields) delete old[field]
        accepts(`${name}: 删除扩展仍解析旧 v1`, () => parse(old))
        for (const field of fields) {
          accepts(`${name}.${field}: 显式 null 保留未知`, () => parse({ ...value, [field]: null }),
            parsed => parsed[field] === null)
          accepts(`${name}.${field}: 可选字段 undefined 保持缺省`, () => parse({ ...value, [field]: undefined }),
            parsed => parsed[field] === undefined)
          for (const invalid of [false, 7, 'invalid', []]) {
            rejects(`${name}.${field}: 非对象 ${JSON.stringify(invalid)}`, () => parse({ ...value, [field]: invalid }))
          }
        }
      }
      accepts('完整自监控保留阈值和观测', () => api.parseOpsOverview(overview), parsed =>
        JSON.stringify(parsed.self_monitoring) === JSON.stringify(monitoring))
      accepts('未知指标不补零或健康', () => api.parseOpsOverview({ ...overview, self_monitoring: { metrics: [{
        ...metric, status: 'monitoring_unavailable', value: null,
        unknown_reason: 'NOT_COLLECTED', effective_config: unknownConfig,
      }] } }), parsed => parsed.self_monitoring.metrics[0].value === null
        && parsed.self_monitoring.metrics[0].status === 'monitoring_unavailable')
      accepts('metrics null 保留未采集', () => api.parseOpsOverview({ ...overview, self_monitoring: { metrics: null } }),
        parsed => parsed.self_monitoring.metrics === null)
      for (const field of ['observed_at', 'fresh_until']) {
        accepts(`${field} null 保留原始状态交由 UI 复核`, () => api.parseOpsOverview({ ...overview,
          self_monitoring: { metrics: [{ ...metric, [field]: null }] } }), parsed =>
          parsed.self_monitoring.metrics[0][field] === null && parsed.self_monitoring.metrics[0].status === 'healthy')
      }
      for (const status of ['healthy', 'degraded', 'unavailable', 'unknown', 'monitoring_unavailable']) {
        accepts(`自监控状态 ${status}`, () => api.parseOpsOverview({ ...overview,
          self_monitoring: { metrics: [{ ...metric, status }] } }), parsed => parsed.self_monitoring.metrics[0].status === status)
      }
      accepts('过期观测保留原始健康状态和原因，UI 决定当前状态', () => api.parseOpsOverview({ ...overview,
        self_monitoring: { metrics: [{ ...metric,
          observed_at: new Date(Date.parse(overview.generated_at) - 120000).toISOString(),
          fresh_until: new Date(Date.parse(overview.generated_at) - 60000).toISOString(),
        }] } }), parsed => parsed.self_monitoring.metrics[0].status === 'healthy'
          && parsed.self_monitoring.metrics[0].unknown_reason === null)
      rejects('重复 metric_id 即使状态不同也拒绝', () => api.parseOpsOverview({ ...overview,
        self_monitoring: { metrics: [metric, { ...metric, status: 'degraded' }] } }))
      for (const freshUntil of [metric.observed_at, new Date(Date.parse(metric.observed_at) - 1).toISOString()]) {
        rejects('观测有效期必须晚于观测时间', () => api.parseOpsOverview({ ...overview,
          self_monitoring: { metrics: [{ ...metric, fresh_until: freshUntil }] } }))
      }
      for (const [field, invalidValues] of Object.entries({
        metric_id: [undefined, null, '', 'bad metric', '<script>'],
        status: [undefined, null, 'ok', true], value: [undefined, '1', -1, Number.NaN, Infinity],
        unit: [undefined, 1], observed_at: [undefined, 'yesterday', '2026-02-30T00:00:00Z'],
        fresh_until: [undefined, 'tomorrow', 1], unknown_reason: [undefined, false],
      })) {
        for (const value of invalidValues) rejects(`metric.${field}=${String(value)}`, () => api.parseOpsOverview({
          ...overview, self_monitoring: { metrics: [{ ...metric, [field]: value }] },
        }))
      }
      rejects('self_monitoring.metrics 缺失', () => api.parseOpsOverview({ ...overview, self_monitoring: {} }))
      for (const value of [undefined, {}, false, [null]]) rejects(`非法 metrics ${String(value)}`,
        () => api.parseOpsOverview({ ...overview, self_monitoring: { metrics: value } }))
      // 阈值配置在三个响应和指标内部复用；缺字段与非法数值不能默认为“未配置”。
      for (const [field, values] of Object.entries({ warning: [undefined, -1, '3'], critical: [undefined, -1, Infinity],
        unit: [undefined, true], window_seconds: [undefined, -1, '300'], source: [undefined, false] })) {
        for (const value of values) {
          const bad = { ...config, [field]: value }
          rejects(`overview 配置 ${field}=${String(value)}`, () => api.parseOpsOverview({ ...overview,
            self_monitoring: { ...monitoring, regeneration_config: bad } }))
          rejects(`metric 配置 ${field}=${String(value)}`, () => api.parseOpsOverview({ ...overview,
            self_monitoring: { metrics: [{ ...metric, effective_config: bad }] } }))
          rejects(`detail 配置 ${field}=${String(value)}`, () => api.parseOpsRunDetail({ ...detail, regeneration_config: bad }))
          rejects(`alert 配置 ${field}=${String(value)}`, () => api.parseOpsAlert({ ...alert, effective_config: bad }))
        }
      }
      accepts('最终题目与旧审核证据保持各自版本', () => api.parseOpsRunDetail(detail), parsed =>
        JSON.stringify(parsed.review_versions) === JSON.stringify(versions))
      accepts('review_versions 所有未知保留 null', () => api.parseOpsRunDetail({ ...detail,
        review_versions: { final_content_revision: null, final_questions: null, required_scopes: null, evidence: null } }),
      parsed => Object.values(parsed.review_versions).every(value => value === null))
      for (const field of ['final_content_revision', 'final_questions', 'required_scopes', 'evidence']) {
        const missing = { ...versions }
        delete missing[field]
        rejects(`review_versions.${field} 缺失`, () => api.parseOpsRunDetail({ ...detail, review_versions: missing }))
        rejects(`review_versions.${field} undefined`, () => api.parseOpsRunDetail({ ...detail,
          review_versions: { ...versions, [field]: undefined } }))
      }
      const badVersions = [
        { final_questions: [{}] }, { final_questions: [{ question_id: null, content_revision: 'r2' }] },
        { final_questions: [{ question_id: 'q1' }] }, { final_questions: [{ question_id: 'q1', content_revision: 2 }] },
        { required_scopes: ['difficulty', null] }, { evidence: [null] },
        ...['question_id', 'content_revision', 'scope', 'status'].map(field => ({ evidence: [{ ...versions.evidence[0], [field]: undefined }] })),
        { evidence: [{ ...versions.evidence[0], status: 'all_passed' }] },
        { final_questions: [versions.final_questions[0], versions.final_questions[0]] },
        { final_questions: [versions.final_questions[0], { ...versions.final_questions[0], content_revision: 'other-r3' }] },
        ...['', 'bad question', 'q\n'].map(question_id => ({ final_questions: [{ question_id, content_revision: 'r2' }] })),
      ]
      badVersions.forEach((bad, index) => rejects(`非法审核证据 ${index}`, () => api.parseOpsRunDetail({
        ...detail, review_versions: { ...versions, ...bad },
      })))
      for (const rule of ['monitoring_pipeline_failure', 'capacity_warning', 'notification_failure', 'future_monitoring_rule']) {
        accepts(`规则原标识 ${rule}`, () => api.parseOpsAlert({ ...alert, rule_id: rule }), parsed => parsed.rule_id === rule)
      }
      for (const rule of [undefined, null, '', 'with space', '../rule', '<script>', 'rule\n', 'a'.repeat(513)]) {
        rejects(`不安全 rule ${String(rule)}`, () => api.parseOpsAlert({ ...alert, rule_id: rule }))
      }
      for (const field of ['impact', 'owner_module', 'manual_action_required', 'next_step']) {
        const missing = { ...guidance }
        delete missing[field]
        rejects(`guidance.${field} 缺失`, () => api.parseOpsAlert({ ...alert, guidance: missing }))
        rejects(`guidance.${field} 非法类型`, () => api.parseOpsAlert({ ...alert,
          guidance: { ...guidance, [field]: field === 'manual_action_required' ? 'true' : false } }))
      }
      return checks
    }, realData)
    assert.deepEqual(results.filter(result => !result.ok), [], '解析矩阵必须逐项通过，拒绝必须使用 INVALID_OPS_RESPONSE')
    console.log(`  扩展契约断言 ${results.length} 项`)
  })

  await check('正式 trace 返回异步未接入，安全与非法路径均不产生正文请求或跳转', async () => {
    await checkNoTraceSideEffects(async () => {
      const result = await page.evaluate(async () => {
        const { realOpsClient } = await import('/src/api/adminOps.ts')
        const pending = realOpsClient.openTrace('/phoenix/projects/synthetic/traces/synthetic')
        const promise = pending instanceof Promise
        const response = await pending
        const closed = []
        for (const path of ['https://example.test/trace', '//example.test/trace', '/trace?token=fake']) {
          const result = realOpsClient.openTrace(path)
          closed.push(result instanceof Promise && (await result).status === 'not_integrated')
        }
        return { promise, response, closed }
      })
      assert.equal(result.promise, true)
      assert.equal(result.response.status, 'not_integrated')
      assert.ok(result.response.message.length > 0)
      assert.ok(result.closed.every(Boolean))
    })
  })

  await check('DEV 四种正文结果均异步返回且不访问 Phoenix', async () => {
    await checkNoTraceSideEffects(async () => {
      const results = await page.evaluate(async () => {
        const { createDemoOpsClient } = await import('/src/api/adminOpsDemo.ts')
        const scenarios = { trace_denied: 'denied', trace_audit_failed: 'audit_failed',
          trace_expired: 'expired', trace_simulated_success: 'simulated_success' }
        const results = []
        for (const [scenario, expected] of Object.entries(scenarios)) {
          const client = createDemoOpsClient(scenario)
          const pending = client.openTrace('/phoenix/projects/synthetic/traces/synthetic')
          results.push({ scenario, expected, promise: pending instanceof Promise, response: await pending })
        }
        return results
      })
      for (const result of results) {
        assert.equal(result.promise, true, result.scenario)
        assert.equal(result.response.status, result.expected, result.scenario)
        assert.ok(result.response.message.length > 0, result.scenario)
      }
    })
  })

  await check('筛选竞态丢弃旧响应，刷新失败保留已加载数据', async () => {
    let release
    delayed = { owner: 'old-user', promise: new Promise(resolve => { release = resolve }), release: () => release() }
    await page.getByLabel('归属账号 ID', { exact: true }).fill('old-user')
    const oldRequest = page.waitForRequest(request => request.url().includes('owner_user_id=old-user'))
    await page.getByRole('button', { name: '应用筛选', exact: true }).click()
    await oldRequest
    await page.getByLabel('归属账号 ID', { exact: true }).fill('new-user')
    await page.getByRole('button', { name: '应用筛选', exact: true }).click()
    await page.getByRole('button', { name: '查看运行 fresh-run', exact: true }).waitFor()
    delayed.release()
    await page.waitForTimeout(100)
    assert.equal(await page.getByRole('button', { name: '查看运行 stale-run', exact: true }).count(), 0)
    realFailure = 503
    await page.getByRole('button', { name: '刷新第一页', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: /刷新失败/ }).waitFor()
    assert.equal(await page.getByRole('button', { name: '查看运行 fresh-run', exact: true }).count(), 1)
    realFailure = 0
  })

  await check('追加分页后刷新失败保留完整集合及暂停状态，成功刷新再恢复首屏轮询', async () => {
    await nav('平台概览').click()
    await nav('出题运行').click()
    const rows = page.getByRole('button', { name: /^查看运行 / })
    await rows.first().waitFor()
    const second = structuredClone(realData.runs)
    second.items = [second.items[0], { ...second.items[1], run_id: 'synthetic-appended-run' }]
    second.page = { ...second.page, has_more: false, next_cursor: null }
    const append = nextResponse('/api/admin/ops/runs', 'GET', second, { query: query => query.has('cursor') })
    await page.getByRole('button', { name: '加载更多', exact: true }).click()
    await append.done
    await page.getByRole('button', { name: '查看运行 synthetic-appended-run', exact: true }).waitFor()
    const loaded = await rows.evaluateAll(elements => elements.map(element => element.getAttribute('aria-label')))
    assert.equal(loaded.length, realData.runs.items.length + 1, '重复运行合并，新增运行追加')
    await freezeClock()
    try {
      const failure = nextResponse('/api/admin/ops/runs', 'GET', { detail: { code: 'OPS_DATA_UNAVAILABLE' } }, { status: 503 })
      await page.getByRole('button', { name: '刷新第一页', exact: true }).click()
      await failure.done
      await page.getByRole('alert').filter({ hasText: /刷新失败/ }).waitFor()
      assert.deepEqual(await rows.evaluateAll(elements => elements.map(element => element.getAttribute('aria-label'))), loaded)
      await page.getByText(/已追加分页，自动刷新暂停/).waitFor()
      const before = calls.filter(call => call.path === '/api/admin/ops/runs').length
      await page.clock.runFor(31000)
      await visibility(true)
      await visibility(false)
      await renderSettled()
      assert.equal(calls.filter(call => call.path === '/api/admin/ops/runs').length, before,
        '失败后的追加集合在定时和 visible 事件中都保持暂停')
      await page.getByRole('button', { name: '刷新第一页', exact: true }).click()
      await page.getByText(/首屏每 15 秒自动刷新/).waitFor()
      assert.equal(await rows.count(), realData.runs.items.length)
      const refreshed = calls.filter(call => call.path === '/api/admin/ops/runs').length
      const poll = page.waitForRequest(request => new URL(request.url()).pathname === '/api/admin/ops/runs')
      await page.clock.runFor(16000)
      await poll
      assert.ok(calls.filter(call => call.path === '/api/admin/ops/runs').length > refreshed)
    } finally { await page.clock.resume() }
  })

  await check('自监控九类观测、未知值与实际生效配置，时钟偏差和过期不假报健康', async () => {
    const original = structuredClone(realData.overview)
    const serverNow = Date.parse(realData.overview.generated_at) + 3600000
    const sample = structuredClone(realData.overview)
    sample.generated_at = new Date(serverNow).toISOString()
    const labels = ['采集延迟', '摘要写入失败', '事件丢弃', 'Phoenix 导出积压', '告警评估', '清理结果',
      '通知失败', '运行与追踪关联缺失', '存储容量']
    assert.equal(sample.self_monitoring.metrics.length, 9)
    sample.self_monitoring.metrics = sample.self_monitoring.metrics.map((metric, index) => ({ ...metric,
      status: index === 1 ? 'monitoring_unavailable' : index === 2 ? 'unknown' : 'healthy',
      value: index === 1 || index === 2 ? null : metric.value,
      observed_at: new Date(serverNow - 5000).toISOString(),
      fresh_until: new Date(serverNow + (index === 2 ? -1000 : 3000)).toISOString(),
      unknown_reason: index === 1 ? 'MONITORING_UNAVAILABLE' : index === 2 ? 'OBSERVATION_STALE' : null,
    }))
    realData.overview = sample
    await freezeClock()
    try {
      await nav('平台概览').click()
      const health = card(page, '运维链路健康')
      await health.getByRole('heading', { name: labels[0], exact: true }).waitFor()
      for (const label of labels) await health.getByRole('heading', { name: label, exact: true }).waitFor()
      const ingestion = card(health, labels[0])
      await ingestion.getByText('健康', { exact: true }).waitFor()
      assert.equal(await fact(ingestion, 'warning 阈值').innerText(), '1,000')
      assert.equal(await fact(ingestion, 'critical 阈值').innerText(), '5,000')
      assert.equal(await fact(ingestion, '配置来源').innerText(), 'environment')
      const unavailable = card(health, labels[1])
      await unavailable.getByText('监控不可用', { exact: true }).waitFor()
      assert.match(await fact(unavailable, '观测值').innerText(), /^未知/)
      await card(health, labels[2]).getByText('未知', { exact: true }).first().waitFor()
      await page.clock.runFor(4000)
      await ingestion.getByText('未知', { exact: true }).first().waitFor()
      assert.equal(await ingestion.getByText('健康', { exact: true }).count(), 0)
      await ingestion.getByText(/观测已过期或未提供新鲜度证据/).waitFor()
      const reload = page.waitForRequest(request => new URL(request.url()).pathname === '/api/admin/ops/overview')
      await visibility(true)
      await visibility(false)
      await reload
      await ingestion.getByText('未知', { exact: true }).first().waitFor()
      assert.equal(await ingestion.getByText('健康', { exact: true }).count(), 0,
        '相同 generated_at 的 visible 重读不得延长证据有效期')
    } finally {
      realData.overview = original
      await page.clock.resume()
    }
  })

  await check('逐题最终 revision、仅难度、冲突证据与实际完成范围分别展示', async () => {
    const original = structuredClone(realData.detail)
    const questions = ['synthetic-old', 'synthetic-difficulty', 'synthetic-conflict', 'synthetic-pass', 'synthetic-identity']
      .map(question_id => ({ question_id, content_revision: 'question-r2' }))
    const evidence = (index, scope, status, revision = 'question-r2') => ({
      question_id: questions[index].question_id, content_revision: revision, scope, status,
    })
    realData.detail = { ...original, run: structuredClone(realData.runs.items[0]), review_versions: {
      final_content_revision: 'batch-r9', final_questions: questions, required_scopes: ['difficulty', 'correctness'],
      evidence: [evidence(0, 'difficulty', 'passed', 'question-r1'), evidence(0, 'correctness', 'passed', 'question-r1'),
        evidence(1, 'difficulty', 'passed'), evidence(2, 'difficulty', 'passed'),
        evidence(2, 'correctness', 'passed'), evidence(2, 'correctness', 'failed'),
        evidence(3, 'difficulty', 'passed'), evidence(3, 'correctness', 'passed'),
        evidence(3, 'correctness', 'failed', 'question-r1')],
    }, regeneration_config: { warning: 3, critical: 7, unit: 'attempts', window_seconds: 0, source: 'synthetic_config' } }
    try {
      await nav('出题运行').click()
      await page.getByRole('button', { name: /^查看运行 / }).first().click()
      const drawer = page.getByRole('dialog')
      const review = card(drawer, '版本与审核范围')
      await review.getByRole('heading', { name: '版本与审核范围', exact: true }).waitFor()
      assert.equal(await fact(review, '最终交付内容集合版本').innerText(), 'batch-r9')
      const item = index => review.getByText(questions[index].question_id, { exact: true }).locator('xpath=ancestor::li[1]')
      assert.match(await fact(item(0), '当前版本实际通过范围').innerText(), /尚无当前版本明确通过证据/)
      assert.match(await fact(item(1), '要求范围未获通过证据').innerText(), /正确|correctness/)
      assert.doesNotMatch(await fact(item(1), '要求范围未获通过证据').innerText(), /全部要求范围/)
      assert.match(await fact(item(2), '当前版本实际完成审核范围').innerText(), /正确|correctness/,
        '失败是完成审核，不能从实际完成范围中抹去')
      assert.doesNotMatch(await fact(item(2), '当前版本实际通过范围').innerText(), /正确|correctness/,
        '同一最终版本同一 scope 既通过又失败不能算通过')
      assert.match(await fact(item(2), '要求范围未获通过证据').innerText(), /正确|correctness/)
      assert.match(await fact(item(3), '要求范围未获通过证据').innerText(), /已提供全部要求范围/,
        '旧版本失败不得覆盖最终版本通过')
      assert.match(await fact(item(4), '当前版本实际完成审核范围').innerText(), /尚无当前版本完成审核证据/,
        '相同 revision 的其他题目证据不能借用')
      await review.locator('summary').click()
      await review.getByText(/不覆盖当前最终内容版本/).first().waitFor()
      const regen = card(drawer, '重出与降级')
      assert.equal(await fact(regen, 'warning 阈值').innerText(), '3')
      assert.equal(await fact(regen, 'critical 阈值').innerText(), '7')
      assert.equal(await fact(regen, '窗口（秒）').innerText(), '0')
      await page.keyboard.press('Escape')
    } finally { realData.detail = original }
  })

  await check('正式正文访问说明可在 trace 未确认时展开，检查保持未接入且只有一个 dialog', async () => {
    const original = structuredClone(realData.detail)
    realData.detail = { ...original, run: { ...realData.runs.items[0], trace: { ...realData.runs.items[0].trace,
      availability: 'unknown', viewer_path: null, verified_at: null } } }
    try {
      await page.getByRole('button', { name: /^查看运行 / }).first().click()
      const drawer = page.getByRole('dialog')
      await drawer.locator('summary').filter({ hasText: '查看正文访问说明' }).click()
      assert.equal(await page.getByRole('dialog').count(), 1, '正文说明是 inline details，不新增嵌套 dialog')
      await checkNoTraceSideEffects(async () => {
        await drawer.getByRole('button', { name: '检查正文访问条件', exact: true }).click()
        await drawer.getByText(/未接入/).first().waitFor()
      })
      await page.keyboard.press('Escape')
    } finally { realData.detail = original }
  })

  await check('依赖在静态快照上随时间过期，失败轮询及 visible 复核不恢复陈旧健康', async () => {
    const original = structuredClone(realData.dependencies)
    const now = Date.parse(original.generated_at) + 3600000
    const dependency = { ...original.items[0], dependency_id: 'synthetic-aging-dependency', status: 'healthy',
      checked_at: new Date(now - 5000).toISOString(), fresh_until: new Date(now + 3000).toISOString() }
    realData.dependencies = { ...original, generated_at: new Date(now).toISOString(), items: [dependency],
      page: { ...original.page, has_more: false, next_cursor: null } }
    await freezeClock()
    try {
      await nav('依赖状态').click()
      const dependencyCard = page.locator('section').filter({ has: page.getByRole('heading', { name: /synthetic-aging-dependency/ }) })
      await dependencyCard.getByText('可用', { exact: true }).waitFor()
      realFailure = 503
      await page.clock.runFor(4000)
      await dependencyCard.getByText('未知', { exact: true }).first().waitFor()
      assert.equal(await dependencyCard.getByText('可用', { exact: true }).count(), 0)
      const failed = page.waitForRequest(request => new URL(request.url()).pathname === '/api/admin/ops/dependencies')
      await page.clock.runFor(12000)
      await failed
      await page.getByRole('alert').filter({ hasText: /刷新失败/ }).waitFor()
      await dependencyCard.getByText('未知', { exact: true }).first().waitFor()
      realFailure = 0
      const refreshed = page.waitForRequest(request => new URL(request.url()).pathname === '/api/admin/ops/dependencies')
      await visibility(true)
      await visibility(false)
      await refreshed
      await dependencyCard.getByText('未知', { exact: true }).first().waitFor()
      assert.equal(await dependencyCard.getByText('可用', { exact: true }).count(), 0,
        '同一个 generated_at 在 visible 后不可重新获得新鲜度')
    } finally {
      realFailure = 0
      realData.dependencies = original
      await page.clock.resume()
    }
  })

  await check('平台统计失败与账号页面独立，新通知重复查询不重复提醒', async () => {
    legacyFailure = true
    await nav('平台概览').click()
    await page.getByRole('alert').filter({ hasText: '平台统计刷新失败' }).waitFor()
    await page.getByRole('heading', { name: '采集窗口与覆盖范围' }).waitFor()
    await nav('账号管理').click()
    await page.getByLabel('fake-teacher显示名称').waitFor()
    assert.equal(await page.getByLabel('fake-teacher显示名称').inputValue(), '合成教师')
    realData.notifications = { ...realData.notifications, unread_count: 60,
      items: realData.notifications.items.map(item => ({ ...item, read: true })) }
    await page.getByRole('button', { name: '管理员通知', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '管理员通知', exact: true })
    await dialog.getByRole('button', { name: '刷新通知', exact: true }).click()
    await page.getByLabel('60 条未读通知').waitFor({ state: 'attached' })
    await dialog.getByRole('button', { name: '标记全部已读', exact: true }).click()
    await dialog.getByRole('status').filter({ hasText: '全部通知已标记为已读' }).waitFor()
    assert.deepEqual(readPayload, { ids: null }, '全部已读必须包含未展示的通知')
    for (let i = 0; i < 2; i++) {
      await dialog.getByRole('button', { name: '刷新通知', exact: true }).click()
      await dialog.getByRole('button', { name: '刷新通知', exact: true }).waitFor()
    }
    assert.equal(await page.getByText(/收到 .* 条新的运维通知/).count(), 0)
    await page.keyboard.press('Escape')
    legacyFailure = false
  })

  await check('通知滑动窗口回流不重复提醒旧通知', async () => {
    const previous = realData.notifications.items.find(item => item.kind.startsWith('ops_'))
    const filler = Array.from({ length: 49 }, (_, index) => ({ ...previous, kind: 'bank_ready',
      id: `synthetic-filler-${index}`, title: `合成普通通知 ${index}`, read: true, ops_alert_id: null, ops_episode_no: null }))
    const fresh = { ...previous, id: 'synthetic-new-notification', title: '合成新增运维通知', read: false }
    realData.notifications = { unread_count: 1, items: [fresh, ...filler] }
    await page.getByRole('button', { name: '管理员通知', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '管理员通知', exact: true })
    await dialog.getByRole('button', { name: '刷新通知', exact: true }).click()
    await dialog.getByText(fresh.title, { exact: true }).waitFor()
    await page.getByText('收到 1 条新的运维通知', { exact: true }).last().waitFor({ state: 'attached' })
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: '关闭提示', exact: true }).click()
    realData.notifications = { unread_count: 1, items: [{ ...previous, read: false }, ...filler] }
    await page.getByRole('button', { name: '管理员通知', exact: true }).click()
    await dialog.getByRole('button', { name: '刷新通知', exact: true }).click()
    await dialog.getByText(previous.title, { exact: true }).waitFor()
    await page.waitForTimeout(100)
    assert.equal(await page.getByText(/收到 .* 条新的运维通知/).count(), 0)
    await page.keyboard.press('Escape')
  })

  await check('通知迟到 GET 不回滚已读或复活已删条目，写入期间禁止读删竞争', async () => {
    await nav('账号管理').click()
    const base = realData.notifications.items[0]
    const first = { ...base, id: 'synthetic-notice-read-race', title: '合成通知读竞态', read: false }
    const second = { ...base, id: 'synthetic-notice-delete-race', title: '合成通知删竞态', read: false }
    realData.notifications = { unread_count: 2, items: [first, second] }
    await page.getByRole('button', { name: '管理员通知', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '管理员通知', exact: true })
    await dialog.getByRole('button', { name: '刷新通知', exact: true }).click()
    await dialog.getByRole('heading', { name: first.title, exact: true }).waitFor()
    await freezeClock()
    try {
      const stale = nextResponse('/api/notifications', 'GET', realData.notifications, { hold: true })
      await dialog.getByRole('button', { name: '刷新通知', exact: true }).click()
      await stale.entered
      const write = nextResponse('/api/notifications/read', 'POST', { ok: true }, { hold: true })
      const item = dialog.getByRole('listitem').filter({ hasText: first.title })
      await item.getByRole('button', { name: '标记已读', exact: true }).click()
      await write.entered
      assert.equal(await dialog.getByRole('button', { name: '刷新通知', exact: true }).isDisabled(), true)
      assert.equal(await dialog.getByRole('button', { name: '标记全部已读', exact: true }).isDisabled(), true)
      for (const button of await dialog.getByRole('button', { name: /^删除通知：/ }).all()) {
        assert.equal(await button.isDisabled(), true, '读操作进行中不允许并发删除')
      }
      const postCount = calls.filter(call => call.method === 'POST' && call.path === '/api/notifications/read').length
      // DOM 的连续激活同样不能绕过组件的单飞保护。
      await dialog.getByRole('button', { name: '标记全部已读', exact: true }).evaluate(element => element.click())
      assert.equal(calls.filter(call => call.method === 'POST' && call.path === '/api/notifications/read').length, postCount)
      realData.notifications = { unread_count: 1, items: [{ ...first, read: true }, second] }
      write.release()
      await write.done
      await dialog.getByRole('status').filter({ hasText: '通知已标记为已读' }).waitFor()
      stale.release()
      await stale.done
      await renderSettled()
      await item.getByText(/ · 已读/).waitFor()
      assert.equal(await item.getByRole('button', { name: '标记已读', exact: true }).count(), 0)
      await page.getByLabel('1 条未读通知', { exact: true }).waitFor({ state: 'attached' })

      await dialog.getByRole('button', { name: '刷新通知', exact: true }).waitFor({ state: 'visible' })
      const lateDelete = nextResponse('/api/notifications', 'GET', realData.notifications, { hold: true })
      await dialog.getByRole('button', { name: '刷新通知', exact: true }).click()
      await lateDelete.entered
      await dialog.getByRole('button', { name: `删除通知：${second.title}`, exact: true }).click()
      await dialog.getByRole('status').filter({ hasText: '通知已删除' }).waitFor()
      lateDelete.release()
      await lateDelete.done
      await renderSettled()
      assert.equal(await dialog.getByRole('heading', { name: second.title, exact: true }).count(), 0,
        '写操作前发出的 GET 不得复活已删除通知')
      assert.equal(await page.getByLabel('1 条未读通知', { exact: true }).count(), 0)
      await page.keyboard.press('Escape')
    } finally { await page.clock.resume() }
  })

  await check('通知单条已读和删除失败保留快照，可重试；关闭重开不重复写或抢焦点', async () => {
    const notice = { ...realData.notifications.items[0], id: 'synthetic-notice-retry', title: '合成可重试通知', read: false }
    realData.notifications = { unread_count: 1, items: [notice] }
    await page.getByRole('button', { name: '管理员通知', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '管理员通知', exact: true })
    await dialog.getByRole('button', { name: '刷新通知', exact: true }).click()
    const item = dialog.getByRole('listitem').filter({ hasText: notice.title })
    await item.waitFor()
    await freezeClock()
    try {
      for (const [path, method, buttonName, success] of [
        ['/api/notifications/read', 'POST', '标记已读', '通知已标记为已读'],
        [`/api/notifications/${notice.id}`, 'DELETE', `删除通知：${notice.title}`, '通知已删除'],
      ]) {
        const failure = nextResponse(path, method, { detail: { code: 'SYNTHETIC_FAILURE', message: '合成写入失败' } }, { status: 503 })
        await item.getByRole('button', { name: buttonName, exact: true }).click()
        await failure.done
        await dialog.getByRole('button', { name: '重试通知操作', exact: true }).waitFor()
        assert.equal(await item.count(), 1)
        if (method === 'POST') {
          await item.getByText(/ · 未读/).waitFor()
          await page.getByLabel('1 条未读通知', { exact: true }).waitFor({ state: 'attached' })
        }
        await dialog.getByRole('button', { name: '重试通知操作', exact: true }).click()
        await dialog.getByRole('status').filter({ hasText: success }).waitFor()
        if (method === 'POST') await item.getByText(/ · 已读/).waitFor()
        else assert.equal(await item.count(), 0)
      }

      // 新挂起写入跨 dialog 生命周期，关闭不等于服务端取消或失败。
      realData.notifications = { unread_count: 1, items: [{ ...notice, id: 'synthetic-reopen-write', read: false }] }
      await dialog.getByRole('button', { name: '刷新通知', exact: true }).click()
      await item.getByText(/ · 未读/).waitFor()
      const held = nextResponse('/api/notifications/read', 'POST', { ok: true }, { hold: true })
      await item.getByRole('button', { name: '标记已读', exact: true }).click()
      await held.entered
      const before = calls.filter(call => call.path === '/api/notifications/read' && call.method === 'POST').length
      await page.keyboard.press('Escape')
      await dialog.waitFor({ state: 'hidden' })
      assert.equal(await page.getByRole('button', { name: '管理员通知', exact: true }).evaluate(element => element === document.activeElement), true)
      await page.getByRole('button', { name: '管理员通知', exact: true }).click()
      await dialog.getByRole('status').filter({ hasText: /正在标记/ }).waitFor()
      const close = dialog.getByRole('button', { name: '关闭通知', exact: true })
      await close.focus()
      realData.notifications = { unread_count: 0, items: realData.notifications.items.map(item => ({ ...item, read: true })) }
      held.release()
      await held.done
      await dialog.getByRole('status').filter({ hasText: '通知已标记为已读' }).waitFor()
      assert.equal(calls.filter(call => call.path === '/api/notifications/read' && call.method === 'POST').length, before)
      assert.equal(await close.evaluate(element => element === document.activeElement), true,
        '上一打开轮次的写入完成不得抢走新对话框焦点')
      await item.getByText(/ · 已读/).waitFor()
      await page.keyboard.press('Escape')
    } finally { await page.clock.resume() }
  })

  await check('DEV 正文四种决策通过真实按钮展示，inline 说明不打开第二个 dialog', async () => {
    await setDemo(true)
    await nav('出题运行').click()
    for (const [scenario, message] of [
      ['trace_denied', /独立授权被拒绝/], ['trace_audit_failed', /审计写入失败/],
      ['trace_expired', /正文已过期/], ['trace_simulated_success', /模拟成功/],
    ]) {
      await page.getByLabel('演示场景').selectOption(scenario)
      const opener = page.getByRole('button', { name: /^查看运行 / }).first()
      await opener.waitFor()
      const name = await opener.getAttribute('aria-label')
      await opener.click()
      const drawer = page.getByRole('dialog')
      await drawer.locator('summary').filter({ hasText: '查看正文访问说明' }).click()
      await checkNoTraceSideEffects(async () => {
        await drawer.getByRole('button', { name: '演示正文访问检查', exact: true }).click()
        await drawer.getByRole('status').filter({ hasText: message }).waitFor()
      })
      assert.equal(await page.getByRole('dialog').count(), 1)
      await page.keyboard.press('Escape')
      assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), name)
    }
  })

  await check('校时回拨、空快照筛选和未来观测不让已失效证据恢复健康', async () => {
    await setDemo(false)
    const original = structuredClone(realData.dependencies)
    const serverNow = await page.evaluate(() => Date.now())
    const dependency = { ...original.items[0], dependency_id: 'synthetic-monotonic', status: 'healthy',
      checked_at: new Date(serverNow - 5000).toISOString(), fresh_until: new Date(serverNow + 3000).toISOString() }
    realData.dependencies = { ...original, generated_at: new Date(serverNow).toISOString(),
      items: [dependency, { ...dependency, dependency_id: 'synthetic-future',
        checked_at: new Date(serverNow + 1000).toISOString(), fresh_until: new Date(serverNow + 60000).toISOString() }],
      page: { ...original.page, has_more: false, next_cursor: null } }
    await freezeClock()
    try {
      await nav('依赖状态').click()
      const current = page.getByRole('heading', { name: /synthetic-monotonic/ }).locator('xpath=ancestor::section[1]')
      const future = page.getByRole('heading', { name: /synthetic-future/ }).locator('xpath=ancestor::section[1]')
      await current.getByText('可用', { exact: true }).waitFor()
      await future.getByText('未知', { exact: true }).first().waitFor()
      await page.clock.runFor(4000)
      await current.getByText('观测已过期／未知', { exact: true }).waitFor()
      assert.equal(await future.getByText('可用', { exact: true }).count(), 0)
      await page.clock.setSystemTime(new Date(serverNow - 60000))
      await page.clock.runFor(1000)
      assert.equal(await current.getByText('可用', { exact: true }).count(), 0, '本机回拨不能复活已过期观测')
      const response = page.waitForResponse(value => new URL(value.url()).pathname === '/api/admin/ops/dependencies')
      await page.getByRole('button', { name: '应用筛选', exact: true }).click()
      await response
      await current.getByText('观测已过期／未知', { exact: true }).waitFor()
      assert.equal(await current.getByText('可用', { exact: true }).count(), 0, '筛选暂时清空数据不重置旧快照时钟')
      await page.getByLabel('证据来源（筛选已加载记录）').selectOption(dependency.source)
      assert.equal(await current.getByText('可用', { exact: true }).count(), 0)
    } finally { realData.dependencies = original; await page.clock.resume() }
  })

  await check('自监控关联导航、未知规则指引和告警 ID 尊重显式时间选择', async () => {
    await setDemo(true)
    await page.getByLabel('演示场景').selectOption('partial')
    await nav('平台概览').click()
    await page.getByRole('heading', { name: '运维链路健康', exact: true }).waitFor()
    await page.getByRole('button', { name: '查看容量异常（近 24 小时新建）', exact: true }).click()
    await page.getByRole('heading', { name: /容量异常 · 第/ }).waitFor()
    assert.equal(await page.getByRole('combobox', { name: '规则', exact: true }).inputValue(), 'capacity_warning')
    await page.getByRole('button', { name: '重置查询', exact: true }).click()
    await page.getByRole('heading', { name: /未识别规则（future_monitoring_rule）/ }).waitFor()
    const unknown = page.getByRole('heading', { name: /未识别规则（future_monitoring_rule）/ }).locator('xpath=ancestor::article[1]')
    await unknown.locator('summary').filter({ hasText: '只读排障指引' }).click()
    await unknown.getByText(/页面不推断其恢复逻辑/).waitFor()
    assert.equal(await page.getByRole('combobox', { name: '规则', exact: true }).locator('option[value="future_monitoring_rule"]').count(), 0)
    const range = page.getByRole('combobox', { name: '时间窗口', exact: true })
    const alertId = page.getByLabel('告警 ID（通知精确定位）')
    await alertId.fill('synthetic-rule-id')
    assert.equal(await range.inputValue(), 'retained')
    await alertId.clear()
    assert.equal(await range.inputValue(), '24h')
    await range.selectOption('24h')
    await alertId.fill('synthetic-rule-id')
    assert.equal(await range.inputValue(), '24h')
    await range.selectOption('custom')
    await alertId.fill('synthetic-rule-id-2')
    assert.equal(await range.inputValue(), 'custom')
    await page.getByRole('button', { name: '重置查询', exact: true }).click()
  })

  await check('四种宽度布局、减少动态效果与页面截图', async () => {
    await setDemo(true)
    await page.getByLabel('演示场景').selectOption('normal')
    await nav('平台概览').click()
    await page.getByRole('heading', { name: '采集窗口与覆盖范围' }).waitFor()
    await page.emulateMedia({ reducedMotion: 'reduce' })
    for (const width of [375, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 })
      await nav('平台概览').click()
      await page.getByRole('heading', { name: '采集窗口与覆盖范围' }).waitFor()
      await card(page, '运维链路健康').screenshot({ path: join(output, `health-${width}.png`) })
      await page.screenshot({ path: join(output, `overview-${width}.png`) })
      for (const section of ['平台概览', '出题运行', '依赖状态', '异常中心', '账号管理', '模型与检索', '账号安全']) {
        await nav(section).click()
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true,
          `${section}在 ${width}px 不能水平溢出`)
        if (['出题运行', '依赖状态', '异常中心'].includes(section)) {
          await page.getByRole('button', { name: '应用筛选', exact: true }).click()
          await page.screenshot({ path: join(output, `${section}-${width}.png`) })
        }
      }
      await page.getByRole('button', { name: '管理员通知', exact: true }).click()
      const notices = page.getByRole('dialog', { name: '管理员通知', exact: true })
      await notices.getByRole('listitem').first().waitFor()
      assert.equal(await notices.evaluate(element => element.scrollWidth <= element.clientWidth + 1), true)
      for (const key of ['Tab', 'Shift+Tab']) {
        // 真实键盘跨越完整焦点集合；每个宽度都必须保持在原生模态框内。
        const count = await notices.locator('button:not([disabled]), summary, a[href], [tabindex="0"]').count()
        for (let index = 0; index <= count; index++) {
          await page.keyboard.press(key)
          assert.equal(await notices.evaluate(element => element.contains(document.activeElement)), true,
            `${width}px 通知 ${key} 焦点不得逃出 dialog`)
        }
      }
      await page.screenshot({ path: join(output, `notifications-${width}.png`) })
      await page.keyboard.press('Escape')
      assert.equal(await page.getByRole('button', { name: '管理员通知', exact: true }).evaluate(element => element === document.activeElement), true)
      await nav('出题运行').click()
      const opener = page.getByRole('button', { name: /^查看运行 / }).first()
      const openerName = await opener.getAttribute('aria-label')
      await opener.focus()
      await page.keyboard.press('Enter')
      const detail = page.getByRole('dialog')
      await detail.getByText(/最终版本审核/).first().waitFor()
      assert.equal(await detail.evaluate(element => element.scrollWidth <= element.clientWidth + 1), true)
      const summary = detail.locator('summary').filter({ hasText: '查看正文访问说明' })
      await summary.focus()
      await page.keyboard.press('Enter')
      assert.equal(await summary.locator('..').evaluate(element => element.open), true)
      for (const key of ['Tab', 'Shift+Tab']) {
        for (let index = 0; index < 12; index++) {
          await page.keyboard.press(key)
          assert.equal(await detail.evaluate(element => element.contains(document.activeElement)), true,
            `${width}px 运行详情 ${key} 焦点不得逃出 dialog`)
        }
      }
      const motion = await detail.evaluate(element => {
        const roots = [element, ...element.querySelectorAll('*')]
        return { reduced: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
          animated: roots.flatMap(node => {
            const style = getComputedStyle(node)
            const durations = style.animationDuration.split(',').map(value => Number.parseFloat(value))
            return style.animationName !== 'none' && durations.some(duration => duration > 0.01)
              ? [{ tag: node.tagName, animation: style.animationName, duration: style.animationDuration }] : []
          }) }
      })
      assert.equal(motion.reduced, true)
      assert.deepEqual(motion.animated, [], `${width}px reduced motion 下不应有持续动画`)
      await page.screenshot({ path: join(output, `run-detail-${width}.png`) })
      await page.keyboard.press('Escape')
      assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), openerName)
    }
    await nav('出题运行').click()
    await page.getByRole('button', { name: /^查看运行 / }).first().click()
    await page.getByRole('dialog').waitFor()
    await page.getByRole('dialog').getByText(/最终版本审核/).first().waitFor()
    await page.screenshot({ path: join(output, 'run-detail-1440.png') })
    await page.setViewportSize({ width: 375, height: 900 })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true)
    await page.screenshot({ path: join(output, 'run-detail-375.png') })
    await page.keyboard.press('Escape')
  })

  assert.deepEqual(unexpected, [], '所有 API 和外部请求必须在合成边界内')
  assert.deepEqual(errors, [], '浏览器不能出现未处理异常')
  const index = await readFile(join(root, 'dist/index.html'), 'utf8')
  assert.ok(index.includes('assets/'))
  const assets = await readdir(join(root, 'dist/assets'))
  for (const asset of assets.filter(name => name.endsWith('.js'))) {
    const source = await readFile(join(root, 'dist/assets', asset), 'utf8')
    assert.equal(source.includes('使用演示数据'), false, '生产构建不得有演示入口')
    assert.equal(source.includes(realData.runs.items[0].run_id), false, '生产构建不得包含演示运行数据')
    for (const marker of ['trace_denied', 'trace_audit_failed', 'trace_simulated_success', 'demo_notification_1', 'demo_user_a']) {
      assert.equal(source.includes(marker), false, `生产构建不得包含演示场景或夹具 ${marker}`)
    }
  }
  await check('生产构建真实浏览器登录无演示开关、场景或 DEV 模块加载', async () => {
    const production = await preview({ root, configFile: join(root, 'vite.auth-test.config.mjs'),
      preview: { host: '127.0.0.1', port: 0, strictPort: true }, logLevel: 'error' })
    const address = production.httpServer.address()
    assert.ok(address && typeof address !== 'string')
    const productionOrigin = `http://127.0.0.1:${address.port}`
    allowedOrigins.add(productionOrigin)
    const productionPage = await context.newPage()
    productionPage.on('pageerror', error => errors.push(error.message))
    const loaded = []
    productionPage.on('request', request => loaded.push(new URL(request.url()).pathname))
    try {
      await productionPage.goto(productionOrigin)
      await productionPage.waitForFunction(() => document.querySelector('h1')?.textContent === '运维后台'
        || Array.from(document.querySelectorAll('label')).some(label => label.textContent?.includes('登录账号')))
      if (await productionPage.getByLabel('登录账号', { exact: true }).isVisible()) {
        await productionPage.getByLabel('登录账号', { exact: true }).fill('fake-ops-admin')
        await productionPage.getByLabel('密码', { exact: true }).fill('Fake-test-password')
        await productionPage.getByRole('button', { name: '进入学习空间', exact: true }).click()
      }
      await productionPage.getByRole('heading', { name: '运维后台', exact: true }).waitFor()
      await productionPage.getByRole('heading', { name: '采集窗口与覆盖范围', exact: true }).waitFor()
      assert.equal(await productionPage.getByLabel('使用演示数据').count(), 0)
      assert.equal(await productionPage.getByLabel('演示场景').count(), 0)
      const productionNav = productionPage.getByRole('navigation', { name: '管理员后台导航' })
      await productionNav.getByRole('button', { name: '出题运行', exact: true }).click()
      await productionPage.getByRole('button', { name: /^查看运行 / }).first().waitFor()
      assert.equal(loaded.some(path => /adminOpsDemo|\/src\/|\/demo-ops\//.test(path)), false,
        '生产页面必须只使用构建资源与真实适配器')
      await productionPage.screenshot({ path: join(output, 'production-no-demo.png') })
    } finally {
      await productionPage.close()
      await new Promise((resolve, reject) => production.httpServer.close(error => error ? reject(error) : resolve()))
      allowedOrigins.delete(productionOrigin)
    }
  })
  assert.equal(overrides.length, 0, '每个单次网络夹具都必须实际命中')
  assert.deepEqual(unexpected, [], '生产和 DEV 全部网络均应留在合成边界内')
  assert.deepEqual(errors, [], '生产和 DEV 均不得出现未处理异常')
  console.log(`运维后台浏览器回归通过：${passed} 组；截图目录 ${output}`)
} catch (error) {
  console.error(await page.locator('body').innerText())
  await page.screenshot({ path: join(output, 'failure.png') })
  throw error
} finally {
  delayed?.release()
  for (const gate of gates) gate.release()
  await context.close()
  await browser.close()
  await server.close()
}
