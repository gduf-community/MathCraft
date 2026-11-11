/* global AbortController, URL, console, document, process, structuredClone, window */
/** 真实应用与浏览器回归；所有 API 为合成响应，不启动后端或访问模型。 */
import assert from 'node:assert/strict'
import { mkdir, readFile, readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const require = createRequire(join(tmpdir(), 'mathcraft-auth-browser', 'package.json'))
const { chromium } = require('playwright-core')
const root = fileURLToPath(new URL('.', import.meta.url))
const output = fileURLToPath(new URL('../output/playwright/ops/', import.meta.url))
const server = await createServer({ root, configFile: join(root, 'vite.auth-test.config.mjs'),
  server: { port: 5182, strictPort: true, hmr: false }, logLevel: 'error' })
await server.listen()
const origin = 'http://127.0.0.1:5182'
const browser = await chromium.launch({ executablePath: process.env.AUTH_BROWSER ?? join(
  homedir(), 'AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe',
), headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = [], unexpected = [], calls = []
const user = { id: 'ops-test-admin', account: 'fake-ops-admin', role: 'admin', identity: '管理员',
  display_name: '合成运维管理员', email_verified: false, password_change_recommended: false }
const legacy = { accounts: { admin_active: 1, teacher_active: 2 }, resources: { banks: 3, documents: 8, papers: 2 },
  admin_contact: '', task_total: 51, task_scope: 'persisted_generation_batches',
  task_status_counts: { completed: 51 }, tasks: [] }
let signedIn = false, realData = null, realFailure = 404, legacyFailure = false
let delayed = null, readPayload = undefined
page.on('pageerror', error => errors.push(error.message))

await context.route('**/*', async route => {
  const req = route.request(), url = new URL(req.url()), path = url.pathname
  if (url.origin !== origin) {
    unexpected.push(url.origin + path)
    return route.abort()
  }
  if (!path.startsWith('/api/')) return route.continue()
  calls.push({ path, method: req.method(), query: url.search })
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
    realData.notifications = { ...realData.notifications, unread_count: 0,
      items: realData.notifications.items.map(item => ({ ...item, read: true })) }
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
  await page.getByRole('button', { name: '登录并进入工作台' }).click()
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
    await page.getByLabel('使用演示数据').check()
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
    await page.getByLabel('使用演示数据').uncheck()
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

  await check('四种宽度布局、减少动态效果与页面截图', async () => {
    await page.getByLabel('使用演示数据').check()
    await page.getByLabel('演示场景').selectOption('normal')
    await nav('平台概览').click()
    await page.getByRole('heading', { name: '采集窗口与覆盖范围' }).waitFor()
    await page.emulateMedia({ reducedMotion: 'reduce' })
    for (const width of [375, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 })
      await nav('平台概览').click()
      await page.getByRole('heading', { name: '采集窗口与覆盖范围' }).waitFor()
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
      await page.screenshot({ path: join(output, `notifications-${width}.png`) })
      await page.keyboard.press('Escape')
      await nav('出题运行').click()
      await page.getByRole('button', { name: /^查看运行 / }).first().click()
      const detail = page.getByRole('dialog')
      await detail.getByText(/最终版本审核/).first().waitFor()
      assert.equal(await detail.evaluate(element => element.scrollWidth <= element.clientWidth + 1), true)
      await page.screenshot({ path: join(output, `run-detail-${width}.png`) })
      await page.keyboard.press('Escape')
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
  }
  console.log(`运维后台浏览器回归通过：${passed} 组；截图目录 ${output}`)
} catch (error) {
  console.error(await page.locator('body').innerText())
  await page.screenshot({ path: join(output, 'failure.png') })
  throw error
} finally {
  delayed?.release()
  await context.close()
  await browser.close()
  await server.close()
}
