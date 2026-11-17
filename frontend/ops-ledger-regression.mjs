/* global AbortController, URL, console, process */
/** 正式临时迁移库 + 实际三条 HTTP 生成路径 + 实际管理员页面；后端模型与 Redis 为替身。 */
import assert from 'node:assert/strict'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchBrowser, withResources } from './regression-resources.mjs'
import { createServer } from 'vite'

assert.ok(process.env.OPS_LEDGER_SEED, '先按本批说明启动隔离后端；不得指向业务数据库')
const seed = JSON.parse(await readFile(process.env.OPS_LEDGER_SEED, 'utf8'))
assert.equal(seed.migration, 'n9a0b1c23456')
assert.match(seed.backend, /^http:\/\/127\.0\.0\.1:\d+$/)
const root = fileURLToPath(new URL('.', import.meta.url))
const output = process.env.OPS_TEST_OUTPUT ?? fileURLToPath(new URL('./.test-results/ops-ledger/', import.meta.url))
await mkdir(output, { recursive: true })
await withResources(async use => {
const server = use(await createServer({ root, configFile: join(root, 'vite.auth-test.config.mjs'),
  server: { port: 5183, strictPort: true, hmr: false, proxy: { '/api': seed.backend, '/media': seed.backend } }, logLevel: 'error' }))
await server.listen()
const origin = 'http://127.0.0.1:5183'
const browser = use(await launchBrowser())
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, serviceWorkers: 'block', timezoneId: 'Asia/Shanghai' })
const teacher = await browser.newContext({ serviceWorkers: 'block' })
const page = await context.newPage()
page.setDefaultTimeout(45000)
const errors = [], unexpected = [], opsCalls = []
page.on('pageerror', error => errors.push(error.message))
await context.route('**/*', async route => {
  const request = route.request(), url = new URL(request.url())
  if (url.origin !== origin) { unexpected.push(url.origin + url.pathname); return route.abort() }
  if (url.pathname.startsWith('/api/admin/ops/')) { assert.equal(request.method(), 'GET'); opsCalls.push(url.pathname) }
  return route.continue()
})
const json = async response => { assert.ok(response.ok(), `${response.status()} ${response.url()}`); return response.json() }
try {
  const login = await json(await teacher.request.post(`${origin}/api/auth/login/account`, {
    headers: { Origin: origin }, data: { account: 'teacher', password: '123123', turnstile_token: '' },
  }))
  const headers = { Authorization: `Bearer ${login.access_token}`, Origin: origin }
  const forbidden = await teacher.request.get(`${origin}/api/admin/ops/runs`, { headers })
  assert.equal(forbidden.status(), 403)
  const chat = await json(await teacher.request.post(`${origin}/api/chat/sessions/${seed.resources.session_id}/messages`, {
    headers, data: { message: '出两道导数选择题，改数据，中等难度' },
  }))
  assert.ok(chat)
  await json(await teacher.request.post(`${origin}/api/generate`, { headers, data: seed.body }))
  const background = await json(await teacher.request.post(`${origin}/api/generate/start`, { headers, data: seed.body }))
  assert.ok(background.task_id)
  await page.goto(origin)
  await page.getByLabel('登录账号', { exact: true }).fill('ops-e2e-admin')
  await page.getByLabel('密码', { exact: true }).fill('Ops-test-only-123')
  await page.getByRole('button', { name: '进入学习空间', exact: true }).click()
  await page.getByRole('heading', { name: '运维后台', exact: true }).waitFor()
  await page.getByText('已记录总数：3', { exact: true }).waitFor()
  const actual = await page.evaluate(async () => {
    const { realOpsClient } = await import('/src/api/adminOps.ts')
    const signal = new AbortController().signal
    const overview = await realOpsClient.getOverview({}, signal)
    const list = await realOpsClient.listRuns({ from: overview.window.from, to: overview.window.to, limit: 20, offset: 0 }, signal)
    const details = await Promise.all(list.items.map(run => realOpsClient.getRun(run.run_id, signal)))
    return { overview, list, details }
  })
  assert.equal(actual.list.items.length, 3)
  assert.equal(actual.overview.status_counts.completed, 3)
  assert.deepEqual(actual.list.items, actual.overview.recent_runs)
  assert.deepEqual(actual.details.map(detail => detail.run), actual.list.items)
  assert.equal(new Set(actual.list.items.map(run => run.run_id)).size, 3)
  assert.ok(actual.list.items.every(run => run.requested_count === 2 && run.delivered_count === 2 && run.batch_id && run.status === 'completed'))
  assert.equal(actual.list.items.filter(run => run.entrypoint === 'conversation' && run.session_id === seed.resources.session_id).length, 1)
  assert.equal(actual.list.items.filter(run => run.entrypoint === 'parameterized' && run.task_id === background.task_id).length, 1)
  assert.equal(actual.list.items.filter(run => run.entrypoint === 'parameterized' && run.task_id === null).length, 1)
  await page.getByRole('navigation', { name: '管理员后台导航' }).getByRole('button', { name: '出题运行', exact: true }).click()
  for (const run of actual.list.items) {
    await page.getByRole('button', { name: `查看运行 ${run.run_id}`, exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '运行详情', exact: true })
    await dialog.getByText(run.batch_id, { exact: true }).waitFor()
    await dialog.getByText(run.owner_user_id, { exact: true }).waitFor()
    for (const [label, expected] of [['请求数量', '2'], ['已保存数量', '2']]) {
      assert.equal(await dialog.getByText(label, { exact: true }).locator('..').locator('dd').innerText(), expected)
    }
    await page.screenshot({ path: join(output, `${run.entrypoint}-${run.task_id ? 'background' : 'direct'}.png`) })
    await page.keyboard.press('Escape')
  }
  const again = await page.evaluate(async ids => {
    const { realOpsClient } = await import('/src/api/adminOps.ts')
    return Promise.all(ids.map(id => realOpsClient.getRun(id, new AbortController().signal)))
  }, actual.list.items.map(run => run.run_id))
  assert.deepEqual(again.map(detail => detail.run), actual.list.items, '查询不能改写台账事实或观察时间')
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, [])
  await writeFile(join(output, 'result.json'), JSON.stringify({ paths: 3, runs: actual.list.items,
    administratorQueries: opsCalls.length, errors, unexpected, realModelCalls: 0 }, null, 2))
  console.log('PASS 正式迁移 + 三条实际 HTTP 路径 + 管理员三接口 + 页面详情；真实模型调用 0')
} catch (error) { await page.screenshot({ path: join(output, 'failure.png') }); throw error }
finally { await teacher.close() }

})
