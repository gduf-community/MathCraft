/* global process, URL, console, window */
/** 实际 React 面板 + 内存请求调度；离线浏览器，不启动后端或访问网络。 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'

const require = createRequire(join(tmpdir(), 'mathcraft-auth-browser', 'package.json'))
const { chromium } = require('playwright-core')
const stubs = {
  backend: `
    const h = () => window.adminHarness;
    export const listAdminAccounts = (query) => h().list(query);
    export const fetchPlatformOverview = () => h().overview();
    export const createAdminAccount = body => h().create(body);
    export const resetAdminPassword = (id, password) => h().reset(id, password);
    export const setAdminAccountStatus = (id, status) => h().status(id, status);
    export const updateAdminAccount = async () => {};
  `,
  auth: `
    export const validateNewPassword = value => Array.from(value).length < 8 ||
      Array.from(value).length > 64 || new TextEncoder().encode(value).length > 72 ? 'invalid' : undefined;
    export const changePasswordCurrent = (...args) => window.adminHarness.change(...args);
    export const bindEmail = async () => {};
    export const changeEmail = async () => {};
    export const changeUserNo = async () => {};
    export const startEmailChange = async () => {};
    export const unbindEmail = async () => {};
    export const sendEmailCode = async () => {};
    export const getAuthConfig = async () => ({site_key: '', available: false});
    export class ApiError extends Error {}
  `,
  session: 'export const clearSession = () => { window.adminHarness.cleared += 1 };',
  AuthContext: `export const useAuth = () => ({user: {userId:'self', displayName:'管理员',
    username:'fake-admin', role:'admin', emailVerified:false,
    passwordChangeRecommended:true}, setAuthNotice:() => {}, logout:async () => {}});`,
}
const bundle = await build({
  stdin: { contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
    import AdminPanel from './src/components/admin/AdminPanel';
    createRoot(document.getElementById('root')).render(<AdminPanel/>);`,
  resolveDir: fileURLToPath(new URL('.', import.meta.url)), loader: 'jsx' },
  bundle: true, write: false, format: 'iife', jsx: 'automatic',
  plugins: [{ name: 'isolated-admin-dependencies', setup(builder) {
    builder.onResolve({ filter: /\/api\/(backend|auth|session)$|\/store\/AuthContext$/ }, args => ({
      path: args.path.split('/').at(-1), namespace: 'admin-fakes',
    }))
    builder.onLoad({ filter: /.*/, namespace: 'admin-fakes' }, args => ({ contents: stubs[args.path] }))
  } }],
})
const browser = await chromium.launch({ executablePath: process.env.AUTH_BROWSER ?? join(
  homedir(), 'AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe',
), headless: true })
const errors = []
async function mount() {
  const page = await browser.newPage()
  await page.route('**/*', route => route.abort())
  page.on('pageerror', error => errors.push(error.message))
  await page.setContent('<div id="root"></div>')
  await page.evaluate(() => {
    const account = name => ({id:name, account:name, display_name:name, role:'admin', status:'active'})
    window.adminHarness = {
      pending: {}, rejectCreate: false, failLoad: false, lists: 0, cleared: 0, resets: 0, changes: [],
      list(query) {
        this.lists++
        if (this.failLoad) return Promise.reject(new Error('synthetic refresh failure'))
        if (query) return new Promise((resolve, reject) => { this.pending[query] = {resolve, reject} })
        return Promise.resolve([account('self')])
      },
      overview: async () => ({accounts:{admin_active:1}, resources:{}, admin_contact:'',
        task_status_counts:{done:51}, tasks:[], task_total:51, recent_task_limit:50}),
      create() { return this.rejectCreate ? Promise.reject(new Error('synthetic create failure')) : Promise.resolve({}) },
      reset() { this.resets++; return Promise.resolve() },
      status: async () => {},
      change(...args) { this.changes.push(args); return Promise.resolve() },
      finish(query, name) { this.pending[query].resolve([account(name)]) },
    }
  })
  await page.addScriptTag({ content: bundle.outputFiles[0].text })
  await page.getByText('self', {exact:true}).waitFor()
  return page
}
try {
  const page = await mount()
  await page.getByLabel('搜索账号').fill('old')
  await page.waitForFunction(() => window.adminHarness.pending.old)
  await page.getByLabel('搜索账号').fill('new')
  await page.waitForFunction(() => window.adminHarness.pending.new)
  await page.evaluate(() => window.adminHarness.finish('new', 'new-result'))
  await page.getByText('new-result', {exact:true}).waitFor()
  await page.evaluate(() => window.adminHarness.finish('old', 'stale-result'))
  await page.evaluate(() => new Promise(resolve => window.requestAnimationFrame(resolve)))
  assert.equal(await page.getByText('stale-result', {exact:true}).count(), 0)
  assert.equal(await page.getByText('new-result', {exact:true}).count(), 1)
  assert.ok((await page.locator('body').innerText()).includes('持久化生成批次总数：51'))
  await page.close()

  const create = await mount()
  await create.evaluate(() => { window.adminHarness.rejectCreate = true })
  await create.getByLabel('登录账号', {exact:true}).fill('new-account')
  await create.getByLabel('显示名称', {exact:true}).fill('新账号')
  await create.getByLabel('初始密码', {exact:true}).fill('fake-password')
  await create.getByRole('button', {name:'创建', exact:true}).click()
  await create.getByText('synthetic create failure', {exact:true}).waitFor()
  assert.equal(await create.getByLabel('登录账号', {exact:true}).inputValue(), 'new-account')
  await create.evaluate(() => { window.adminHarness.rejectCreate = false; window.adminHarness.failLoad = true })
  await create.getByRole('button', {name:'创建', exact:true}).click()
  await create.getByText('账号已创建，请提醒用户登录后修改初始密码、按需绑定邮箱', {exact:true}).waitFor()
  await create.getByRole('alert').waitFor()
  assert.equal(await create.getByLabel('初始密码', {exact:true}).inputValue(), '')
  await create.close()

  for (const action of ['重置密码', '禁用']) {
    const self = await mount()
    const before = await self.evaluate(() => window.adminHarness.lists)
    if (action === '重置密码') await self.getByLabel('self新密码').fill('fake-password')
    await self.getByRole('button', {name:action, exact:true}).click()
    await self.getByRole('heading', {name:'操作已完成'}).waitFor()
    assert.equal(await self.evaluate(() => window.adminHarness.lists), before)
    await self.getByRole('button', {name:'返回登录'}).click()
    assert.equal(await self.evaluate(() => window.adminHarness.cleared), 1)
    await self.close()
  }

  const own = await mount()
  await own.getByText('你正在使用初始或管理员重置的密码，建议修改。此提醒不影响其他功能。', {exact:true}).waitFor()
  await own.getByLabel('我的当前密码', {exact:true}).fill('fake-old-password')
  await own.getByLabel('我的新密码', {exact:true}).fill('fake-new-password')
  await own.getByLabel('确认我的新密码', {exact:true}).fill('fake-new-password')
  await own.getByRole('button', {name:'验证当前密码并修改'}).click()
  await own.waitForFunction(() => window.adminHarness.changes.length === 1)
  assert.deepEqual(await own.evaluate(() => window.adminHarness.changes[0]), [
    'fake-old-password', 'fake-new-password', 'fake-new-password',
  ])
  assert.equal(await own.evaluate(() => window.adminHarness.resets), 0)
  assert.deepEqual(errors, [])
  console.log('PASS: latest search, persistent totals, mutation feedback, self revocation, own-password reminder')
} finally {
  await browser.close()
}
