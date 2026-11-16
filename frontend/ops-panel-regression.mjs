/* global URL, console, document, process, window */
/** V2 实际页面回归：仅在测试边界构造响应，所有外部请求阻断。 */
import assert from 'node:assert/strict'
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchBrowser, withResources } from './regression-resources.mjs'
import { createServer, preview } from 'vite'

const root = fileURLToPath(new URL('.', import.meta.url))
const output = process.env.OPS_TEST_OUTPUT ?? fileURLToPath(new URL('./.test-results/ops-panel/', import.meta.url))
await withResources(async use => {
const server = use(await createServer({ root, configFile: join(root, 'vite.auth-test.config.mjs'),
  server: { port: 5182, strictPort: true, hmr: false }, logLevel: 'error' }))
await server.listen()
const origin = 'http://127.0.0.1:5182'
const allowedOrigins = new Set([origin])
const browser = use(await launchBrowser())
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, serviceWorkers: 'block',
  timezoneId: 'Asia/Shanghai', reducedMotion: 'reduce' })
const page = await context.newPage()
page.setDefaultTimeout(12000)
const errors = [], unexpected = [], calls = [], passed = []
const user = { id: 'test-admin', account: 'fake-admin', role: 'admin', identity: '管理员',
  display_name: '隔离管理员', email_verified: false, password_change_recommended: false }
const legacy = { accounts: { admin_active: 1, teacher_active: 2 }, resources: { banks: 3, documents: 8, papers: 2 },
  admin_contact: '', task_total: 51, task_scope: 'persisted_generation_batches',
  task_status_counts: { completed: 51 }, tasks: [] }
const statuses = ['accepted', 'running', 'completed', 'failed', 'canceled', 'unknown']
const accepted = new Date(Date.now() - 60_000).toISOString()
const fixture = Array.from({ length: 27 }, (_, index) => ({
  run_id: `test_run_${String(index).padStart(3, '0')}`, entrypoint: index % 2 ? 'conversation' : 'parameterized',
  owner_user_id: 'test-owner', session_id: index % 2 ? 'test-session' : null,
  task_id: index % 2 ? null : 'test-task', bank_id: 'test-bank', document_id: 'test-doc',
  batch_id: statuses[index % 6] === 'completed' ? 'test-batch' : null,
  status: statuses[index % 6], requested_count: index === 5 ? null : 2,
  delivered_count: ['completed', 'failed', 'canceled'].includes(statuses[index % 6]) ? 0 : null,
  error_code: statuses[index % 6] === 'failed' ? 'MODEL_ERROR' : statuses[index % 6] === 'canceled'
    ? 'USER_CANCELED' : statuses[index % 6] === 'unknown' ? 'UNKNOWN' : null,
  accepted_at: accepted, started_at: index % 6 === 0 ? null : accepted,
  finished_at: ['completed', 'failed', 'canceled'].includes(statuses[index % 6]) ? accepted : null,
  last_observed_at: accepted,
})).reverse()
let signedIn = false, failure = 0, detailFailure = 0, empty = false, invalidSchema = false
let releaseOld, oldEntered
const oldArrived = new Promise(resolve => { oldEntered = resolve })
const oldGate = new Promise(resolve => { releaseOld = resolve })
page.on('pageerror', error => errors.push(error.message))
function filtered(params) {
  const owner = params.get('owner_user_id')
  if (owner === 'old-user' || owner === 'new-user') return [{ ...fixture[0], owner_user_id: owner,
    run_id: owner === 'old-user' ? 'stale-run' : 'fresh-run' }]
  return empty ? [] : fixture.filter(run => ['owner_user_id', 'entrypoint', 'status', 'session_id', 'task_id', 'batch_id']
    .every(key => !params.has(key) || run[key] === params.get(key)))
}
function windowFor(params) {
  const to = params.get('to') ?? new Date().toISOString()
  return { from: params.get('from') ?? new Date(Date.parse(to) - 86400000).toISOString(), to, time_basis: 'accepted_at' }
}
await context.route('**/*', async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname
  if (!allowedOrigins.has(url.origin)) { unexpected.push(request.method() + ' ' + url.origin + path); return route.abort() }
  if (!path.startsWith('/api/')) return route.continue()
  calls.push({ path, method: request.method(), params: Object.fromEntries(url.searchParams) })
  const login = () => ({ access_token: 'fake-test-access', token_type: 'bearer', expires_in: 900, user })
  let status = 200, body
  if (path === '/api/auth/config') body = { site_key: '', csrf_token: 'fake-csrf', turnstile_enabled: false,
    available: true, methods: ['account_password'] }
  else if (path === '/api/auth/refresh') { status = signedIn ? 200 : 401; body = signedIn ? login() : { detail: { code: 'TOKEN_EXPIRED', message: '请登录' } } }
  else if (path === '/api/auth/login/account') { signedIn = true; body = login() }
  else if (path === '/api/auth/me') body = { user }
  else if (path === '/api/users/me') body = user
  else if (path === '/api/admin/overview') body = legacy
  else if (path === '/api/admin/accounts') body = []
  else if (path === '/api/admin/rag-settings') body = { active: { embedding_model: 'test', embedding_base_url: '',
    embedding_key_configured: false, embedding_key_masked: null, rerank_model: 'test', rerank_base_url: '',
    rerank_key_configured: false, rerank_key_masked: null }, pending: null,
    vector_store: { backend: 'chroma', path: 'test-vectors', available: true, message: '' },
    rebuild: { status: 'idle', progress: 0, stage: '', error: null }, revision: 1 }
  else if (path === '/api/admin/ops/overview' || path === '/api/admin/ops/runs' || /^\/api\/admin\/ops\/runs\/[^/]+$/.test(path)) {
    assert.equal(request.method(), 'GET')
    const allowed = ['from', 'to', 'owner_user_id', 'entrypoint', 'status', 'session_id', 'task_id', 'batch_id',
      ...(path.endsWith('/runs') ? ['limit', 'offset'] : [])]
    assert.ok([...url.searchParams.keys()].every(key => allowed.includes(key)), '不能发送已删除的 V1 参数')
    const rows = filtered(url.searchParams)
    const meta = { schema_version: invalidSchema ? 'v1' : 'v2', generated_at: new Date().toISOString() }
    if (url.searchParams.get('owner_user_id') === 'old-user') { oldEntered(); await oldGate }
    const isDetail = /^\/api\/admin\/ops\/runs\//.test(path)
    if (failure || (isDetail && detailFailure)) {
      status = isDetail && detailFailure ? detailFailure : failure
      body = { detail: { code: status === 404 && isDetail ? 'OPS_RUN_NOT_FOUND' : status === 503
        ? 'OPS_DATA_UNAVAILABLE' : 'TEST_ERROR', message: 'synthetic-private-error-do-not-echo' } }
    } else if (path.endsWith('/overview')) body = { ...meta, window: windowFor(url.searchParams), total_runs: rows.length,
      status_counts: Object.fromEntries(statuses.map(value => [value, rows.filter(run => run.status === value).length])), recent_runs: rows.slice(0, 10) }
    else if (path.endsWith('/runs')) {
      const limit = Number(url.searchParams.get('limit') ?? 20), offset = Number(url.searchParams.get('offset') ?? 0)
      body = { ...meta, window: windowFor(url.searchParams), items: rows.slice(offset, offset + limit),
        page: { limit, offset, has_more: rows.length > offset + limit } }
    } else body = { ...meta, run: fixture.find(run => run.run_id === decodeURIComponent(path.split('/').at(-1))) ?? fixture[0] }
  } else { unexpected.push(request.method() + ' ' + path); status = 404; body = {} }
  try { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }) }
  catch (error) { if (!request.failure()) throw error }
})
const nav = name => page.getByRole('navigation', { name: '管理员后台导航' }).getByRole('button', { name, exact: true })
const rows = () => page.getByRole('button', { name: /^查看运行 / })
const lastList = () => calls.filter(call => call.path === '/api/admin/ops/runs').at(-1)
const fact = (scope, label) => scope.getByText(label, { exact: true }).locator('..').locator('dd')
async function check(name, action) { await action(); passed.push(name); console.log('PASS ' + name) }
async function refresh() {
  const response = page.waitForResponse(value => new URL(value.url()).pathname === '/api/admin/ops/runs')
  await page.getByRole('button', { name: '刷新第一页', exact: true }).click(); await response
}
try {
  await mkdir(output, { recursive: true })
  await page.goto(origin)
  await page.getByLabel('登录账号', { exact: true }).fill('fake-admin')
  await page.getByLabel('密码', { exact: true }).fill('Fake-test-password')
  await page.getByRole('button', { name: '进入学习空间', exact: true }).click()
  await page.getByRole('heading', { name: '运维后台', exact: true }).waitFor()
  await check('五个保留入口、真实平台统计与概览 V2', async () => {
    assert.equal(await page.getByRole('navigation', { name: '管理员后台导航' }).getByRole('button').count(), 5)
    await page.getByText('持久化生成批次总数：51', { exact: true }).waitFor()
    await page.getByText('已记录总数：27', { exact: true }).waitFor()
    assert.equal(await rows().count(), 10)
    for (const name of ['使用演示数据', '管理员通知', '依赖状态', '异常中心']) assert.equal(await page.getByRole('button', { name, exact: true }).count(), 0)
  })
  await check('响应校验、六状态、null/0和无效数据拒绝', async () => {
    const result = await page.evaluate(async sample => {
      const api = await import('/src/api/adminOps.ts')
      const reject = value => { try { api.parseOpsRun(value); return false } catch { return true } }
      return {
        states: ['accepted', 'running', 'completed', 'failed', 'canceled', 'unknown'].map(status => api.parseOpsRun({ ...sample, status }).status),
        counts: api.parseOpsRun({ ...sample, requested_count: null, delivered_count: 0 }),
        invalid: [{ ...sample, status: 'cancelled' }, { ...sample, requested_count: 0 },
          { ...sample, delivered_count: -1 }, { ...sample, delivered_count: '0' }, { ...sample, task_id: undefined },
          { ...sample, run_id: 'x'.repeat(129) }, { ...sample, run_id: 'bad/id' },
          { ...sample, accepted_at: '2026-11-15T00:00:00' },
          { ...sample, error_code: 'synthetic-private-error-do-not-echo' }].map(reject),
      }
    }, fixture[0])
    assert.deepEqual(result.states, statuses); assert.equal(result.counts.requested_count, null)
    assert.equal(result.counts.delivered_count, 0); assert.ok(result.invalid.every(Boolean))
    const projection = await page.evaluate(async sample => {
      const api = await import('/src/api/adminOps.ts')
      const extra = { unused_extension: { internal_note: 'test-only-do-not-render' } }
      const run = { ...sample, ...extra, quality: { unused: true } }
      const meta = { schema_version: 'v2', generated_at: sample.accepted_at, ...extra }
      const window = { from: new Date(Date.parse(sample.accepted_at) - 1000).toISOString(),
        to: new Date(Date.parse(sample.accepted_at) + 1000).toISOString(), time_basis: 'accepted_at', ...extra }
      const list = api.parseOpsRuns({ ...meta, window, items: [run],
        page: { limit: 20, offset: 0, has_more: false, ...extra } })
      const overview = api.parseOpsOverview({ ...meta, window, total_runs: 1,
        status_counts: { ...Object.fromEntries(['accepted', 'running', 'completed', 'failed', 'canceled', 'unknown']
          .map(status => [status, status === sample.status ? 1 : 0])), ...extra }, recent_runs: [run] })
      const detail = api.parseOpsRunDetail({ ...meta, run })
      return { list, overview, detail }
    }, fixture[0])
    assert.equal(JSON.stringify(projection).includes('unused_extension'), false)
    assert.equal(JSON.stringify(projection).includes('quality'), false)
    assert.equal(projection.detail.run.run_id, fixture[0].run_id)
    assert.equal(projection.overview.total_runs, 1)

  })
  await nav('出题运行').click(); await rows().nth(19).waitFor()
  await check('offset 前后页、固定窗口及每页数量重置', async () => {
    await page.getByRole('button', { name: '下一页', exact: true }).click()
    await page.getByText('第 2 页', { exact: false }).waitFor()
    await rows().nth(6).waitFor(); assert.equal(await rows().count(), 7)
    assert.equal(lastList().params.offset, '20')
    const anchored = { from: lastList().params.from, to: lastList().params.to }
    assert.ok(anchored.from && anchored.to)
    await page.getByRole('button', { name: '上一页', exact: true }).click(); await rows().nth(19).waitFor()
    assert.deepEqual({ from: lastList().params.from, to: lastList().params.to }, anchored)
    await page.getByLabel('每页数量', { exact: true }).selectOption('50'); await rows().nth(26).waitFor()
    assert.equal(lastList().params.offset, '0'); assert.equal(lastList().params.limit, '50')
    assert.equal(await page.getByRole('button', { name: '下一页', exact: true }).isDisabled(), true)
  })
  await check('全部合法筛选、AND 组合、筛选重置页码', async () => {
    await page.getByLabel('归属账号 ID', { exact: true }).fill('unsaved-draft')
    await page.getByRole('button', { name: '重置查询', exact: true }).click()
    assert.equal(await page.getByLabel('归属账号 ID', { exact: true }).inputValue(), '')
    await page.getByLabel('运行状态', { exact: true }).selectOption('canceled')
    await page.getByLabel('出题入口', { exact: true }).selectOption('parameterized')
    await page.getByLabel('归属账号 ID', { exact: true }).fill('test-owner')
    await page.getByLabel('任务 ID', { exact: true }).fill('test-task')
    await page.getByRole('button', { name: '应用筛选', exact: true }).click()
    await page.waitForFunction(() => document.querySelectorAll('[aria-label^="查看运行 "]').length === 4)
    assert.equal(lastList().params.status, 'canceled'); assert.equal(lastList().params.task_id, 'test-task')
    assert.equal(lastList().params.offset, '0')
    await page.getByRole('button', { name: '重置查询', exact: true }).click(); await rows().nth(26).waitFor()
    for (const [label, key, value] of [['会话 ID', 'session_id', 'test-session'], ['批次 ID', 'batch_id', 'test-batch']]) {
      await page.getByLabel(label, { exact: true }).fill(value)
      const response = page.waitForResponse(response => new URL(response.url()).searchParams.get(key) === value)
      await page.getByRole('button', { name: '应用筛选', exact: true }).click()
      await response
      assert.equal(lastList().params[key], value)
      await page.getByRole('button', { name: '重置查询', exact: true }).click(); await rows().nth(26).waitFor()
    }
  })
  await check('详情零值/未知、关联字段、Escape和焦点恢复', async () => {
    const opener = page.getByRole('button', { name: '查看运行 test_run_005', exact: true })
    await opener.click(); const dialog = page.getByRole('dialog', { name: '运行详情', exact: true })
    await dialog.getByRole('heading', { name: '运行结果', exact: true }).waitFor()
    assert.equal(await fact(dialog, '请求数量').innerText(), '未知')
    assert.equal(await fact(dialog, '已保存数量').innerText(), '未知')
    for (let index = 0; index < 6; index++) { await page.keyboard.press('Tab'); assert.ok(await dialog.evaluate(el => el.contains(document.activeElement))) }
    await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' })
    assert.ok(await opener.evaluate(el => el === document.activeElement))
    await page.getByRole('button', { name: '查看运行 test_run_002', exact: true }).click()
    await dialog.getByRole('heading', { name: '运行结果', exact: true }).waitFor()
    assert.equal(await fact(dialog, '已保存数量').innerText(), '0')
    await page.keyboard.press('Escape')
  })
  await check('404仅不存在、503不可用及私有错误不回显', async () => {
    for (const [code, text] of [[404, '运行记录不存在'], [503, '运行数据暂不可用']]) {
      detailFailure = code
      await rows().first().click(); const dialog = page.getByRole('dialog', { name: '运行详情', exact: true })
      await dialog.getByRole('alert').filter({ hasText: text }).waitFor()
      const body = await dialog.innerText(); assert.equal(body.includes('保留期'), false); assert.equal(body.includes('synthetic-private'), false)
      await page.keyboard.press('Escape')
    }
    detailFailure = 0
    for (const [code, text] of [[503, '运行数据暂不可用'], [422, '查询参数无效'], [403, '需要管理员权限']]) {
      failure = code; await refresh(); await page.getByRole('alert').filter({ hasText: text }).waitFor()
      if (code === 503) { assert.equal(await rows().count(), 27); await page.getByText(/以下为上次成功加载的旧数据/).waitFor() }
      if (code === 403) assert.equal(await rows().count(), 0)
      assert.equal((await page.locator('body').innerText()).includes('synthetic-private'), false)
    }
    failure = 0; await refresh(); await rows().nth(26).waitFor()
  })
  await check('有效空台账与无效 schema 分别展示', async () => {
    empty = true; await refresh(); await page.getByText(/当前筛选下没有匹配记录/).waitFor(); assert.equal(await rows().count(), 0)
    empty = false; invalidSchema = true; await refresh(); await page.getByRole('alert').filter({ hasText: '响应格式无效' }).waitFor()
    invalidSchema = false; await refresh(); await rows().nth(26).waitFor()
  })
  await check('自定义超过十四天及未来窗口符合 V2', async () => {
    await page.getByLabel('时间窗口', { exact: true }).selectOption('custom')
    await page.getByLabel('开始时间（本地，包含）', { exact: true }).fill('2026-10-01T08:00')
    await page.getByLabel('结束时间（本地，不包含）', { exact: true }).fill('2027-01-01T08:00')
    const response = page.waitForResponse(value => new URL(value.url()).searchParams.get('from') === '2026-10-01T00:00:00.000Z')
    await page.getByRole('button', { name: '应用筛选', exact: true }).click(); await response
    assert.equal(lastList().params.to, '2027-01-01T00:00:00.000Z')
    await page.getByRole('button', { name: '重置查询', exact: true }).click(); await rows().nth(26).waitFor()
  })
  await check('晚到旧请求不能覆盖新筛选', async () => {
    await page.getByLabel('归属账号 ID', { exact: true }).fill('old-user')
    await page.getByRole('button', { name: '应用筛选', exact: true }).click(); await oldArrived
    await page.getByLabel('归属账号 ID', { exact: true }).fill('new-user')
    await page.getByRole('button', { name: '应用筛选', exact: true }).click()
    await page.getByRole('button', { name: '查看运行 fresh-run', exact: true }).waitFor()
    releaseOld(); await page.waitForTimeout(100)
    assert.equal(await page.getByRole('button', { name: '查看运行 stale-run', exact: true }).count(), 0)
    await page.getByRole('button', { name: '重置查询', exact: true }).click(); await rows().nth(26).waitFor()
  })
  await check('首页轮询、隐藏暂停及翻页后不自动刷新', async () => {
    await page.clock.install()
    await page.clock.pauseAt(new Date(Date.now() + 1000))
    await page.getByLabel('每页数量', { exact: true }).selectOption('20'); await rows().nth(19).waitFor()
    const count = () => calls.filter(call => call.path === '/api/admin/ops/runs').length
    let before = count()
    await page.clock.runFor(16000)
    await page.waitForFunction(() => Array.from(document.querySelectorAll('button')).find(button => button.textContent === '刷新第一页')?.disabled === false)
    assert.ok(count() > before)
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
      document.dispatchEvent(new window.Event('visibilitychange'))
    })
    before = count(); await page.clock.runFor(31000); assert.equal(count(), before)
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
      document.dispatchEvent(new window.Event('visibilitychange'))
    })
    await rows().nth(19).waitFor()
    await page.getByRole('button', { name: '下一页', exact: true }).click(); await rows().nth(6).waitFor()
    before = count(); await page.clock.runFor(31000); assert.equal(count(), before)
    await page.getByRole('button', { name: '刷新第一页', exact: true }).click(); await rows().nth(19).waitFor()
    await page.clock.resume()
  })
  await check('概览跳转沿用窗口和状态条件', async () => {
    await nav('平台概览').click(); await page.getByText('已记录总数：27', { exact: true }).waitFor()
    const overview = page.getByRole('region', { name: '出题运行概览', exact: true })
    await overview.getByRole('button', { name: '已取消 4', exact: true }).click()
    await page.waitForFunction(() => document.querySelectorAll('[aria-label^="查看运行 "]').length === 4)
    assert.equal(lastList().params.status, 'canceled'); assert.ok(lastList().params.from && lastList().params.to)
  })
  await check('移动布局、保留平台/账号/RAG/安全页面', async () => {
    for (const width of [375, 768, 1440]) {
      await page.setViewportSize({ width, height: 1000 })
      for (const name of ['平台概览', '出题运行', '账号管理', '模型与检索', '账号安全']) {
        await nav(name).click()
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name} ${width}px 溢出`)
      }
      await nav('出题运行').click(); await rows().first().waitFor()
      await page.screenshot({ path: join(output, `runs-${width}.png`) })
      await rows().first().click(); const dialog = page.getByRole('dialog', { name: '运行详情', exact: true })
      await dialog.getByRole('heading', { name: '业务关联', exact: true }).waitFor()
      assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
      await page.screenshot({ path: join(output, `detail-${width}.png`) }); await page.keyboard.press('Escape')
    }
  })
  await check('生产构建及浏览器只含 V2 能力', async () => {
    const assets = await readdir(join(root, 'dist/assets'))
    for (const name of assets.filter(value => value.endsWith('.js'))) {
      const source = await readFile(join(root, 'dist/assets', name), 'utf8')
      for (const marker of ['adminOpsDemo', '使用演示数据', '异常中心', '依赖状态', 'trace_simulated_success']) {
        assert.equal(source.includes(marker), false, `产物含旧能力 ${marker}`)
      }
    }
    const production = await preview({ root, configFile: join(root, 'vite.auth-test.config.mjs'),
      preview: { host: '127.0.0.1', port: 0, strictPort: true }, logLevel: 'error' })
    use(production, () => new Promise((resolve, reject) => {
      production.httpServer.close(error => error ? reject(error) : resolve())
    }))
    const address = production.httpServer.address(); assert.ok(address && typeof address !== 'string')
    const productionOrigin = `http://127.0.0.1:${address.port}`; allowedOrigins.add(productionOrigin)
    const built = await context.newPage()
    try {
      await built.goto(productionOrigin)
      await built.getByRole('heading', { name: '运维后台', exact: true }).waitFor()
      await built.getByText('已记录总数：27', { exact: true }).waitFor()
      assert.equal(await built.getByRole('navigation', { name: '管理员后台导航' }).getByRole('button').count(), 5)
    } finally { await built.close() }
  })
  await check('401沿用真实会话失效流程', async () => {
    await nav('出题运行').click(); await rows().first().waitFor()
    failure = 401; signedIn = false
    await refresh()
    await page.getByRole('button', { name: '进入学习空间', exact: true }).waitFor()
    assert.equal(await rows().count(), 0)
  })
  assert.deepEqual(unexpected, []); assert.deepEqual(errors, [])
  assert.ok(calls.filter(call => call.path.startsWith('/api/admin/ops/')).every(call => call.method === 'GET'))
  await writeFile(join(output, 'result.json'), JSON.stringify({ passed, groups: passed.length,
    unexpected, errors, opsRequests: calls.filter(call => call.path.startsWith('/api/admin/ops/')).length }, null, 2))
  console.log(`V2 浏览器回归通过：${passed.length} 组`)
} catch (error) {
  try {
    await page.screenshot({ path: join(output, 'failure.png'), timeout: 10000 })
  } catch (captureError) { console.error('Failure screenshot unavailable:', captureError.message) }
  throw error
} finally {
  releaseOld()
}

})
