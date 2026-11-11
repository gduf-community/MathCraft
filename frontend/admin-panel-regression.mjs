/* global process, URL, console, window, Event */
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
  session: `
    export const getSessionGeneration = () => window.adminHarness.generation;
    export const onSessionCleared = listener => {
      window.adminHarness.listeners.add(listener);
      return () => window.adminHarness.listeners.delete(listener);
    };
    export const clearSession = () => {
      const h = window.adminHarness; h.cleared++; h.generation++;
      for (const listener of h.listeners) listener();
    };
    export class ApiError extends Error { constructor(message, code, status) { super(message); this.code = code; this.status = status; } }
    export const request = (path, init = {}) => {
      const h = window.adminHarness;
      if (path === '/api/admin/rag-settings') {
        if (init.method !== 'PUT' && h.ragFailure) {
          return Promise.reject(h.ragFailure === 'network' ? new TypeError('Failed to fetch')
            : new ApiError('Not Found', 'SYNTHETIC_ERROR', h.ragFailure));
        }
        return init.method === 'PUT' ? h.saveRag(JSON.parse(init.body)) : Promise.resolve(h.rag);
      }
      throw new Error('unexpected API: ' + path);
    };
  `,
  AuthContext: `export const useAuth = () => ({user: {userId:'self', displayName:'管理员',
    username:'fake-admin', role:'admin', emailVerified:false,
    passwordChangeRecommended:true}, setAuthNotice:() => {}, logout:async () => {}});`,
}
const bundle = await build({
  stdin: { contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
    import AdminPanel from './src/components/admin/AdminPanel';
    import {ToastProvider} from './src/store/ToastContext';
    import Toast from './src/components/ui/Toast';
    createRoot(document.getElementById('root')).render(<ToastProvider><AdminPanel/><Toast/></ToastProvider>);`,
  resolveDir: fileURLToPath(new URL('.', import.meta.url)), loader: 'jsx' },
  bundle: true, write: false, format: 'iife', jsx: 'automatic',
  define: { 'import.meta.env.DEV': 'false' },
  plugins: [{ name: 'isolated-admin-dependencies', setup(builder) {
    builder.onResolve({ filter: /\/(backend|auth|session|AuthContext)$/ }, args => ({
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
      generation: 0, listeners: new Set(),
      rag: {
        active: {embedding_model:'fake-embedding', embedding_base_url:'https://embedding.example.test/v1',
          embedding_key_configured:true, embedding_key_masked:null, rerank_model:'fake-rerank',
          rerank_base_url:'https://rerank.example.test/v1', rerank_key_configured:true, rerank_key_masked:null},
        pending:null, vector_store:{backend:'chroma', path:'synthetic-vectors', available:true, message:''},
        rebuild:{status:'idle', progress:0, stage:'', error:null}, revision:1,
      },
      saveRag(body) {
        this.ragWrites = (this.ragWrites ?? 0) + 1;
        return new Promise((resolve, reject) => { this.ragSave = {body, resolve, reject} })
      },
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
  await page.getByRole('navigation', {name:'管理员后台导航'}).getByRole('button', {name:'账号管理', exact:true}).click()
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
  await page.getByRole('navigation', {name:'管理员后台导航'}).getByRole('button', {name:'平台概览', exact:true}).click()
  await page.getByText('持久化生成批次总数：51', {exact:true}).waitFor()
  assert.ok((await page.locator('body').innerText()).includes('持久化生成批次总数：51'))
  await page.close()

  const create = await mount()
  await create.evaluate(() => { window.adminHarness.rejectCreate = true })
  await create.getByLabel('登录账号', {exact:true}).fill('new-account')
  await create.getByLabel('显示名称', {exact:true}).fill('新账号')
  await create.getByLabel('初始密码', {exact:true}).fill('fake-password')
  await create.getByRole('button', {name:'创建', exact:true}).click()
  await create.getByRole('alert').filter({hasText:'synthetic create failure'}).waitFor()
  assert.equal(await create.getByLabel('登录账号', {exact:true}).inputValue(), 'new-account')
  await create.evaluate(() => { window.adminHarness.rejectCreate = false; window.adminHarness.failLoad = true })
  await create.getByRole('button', {name:'创建', exact:true}).click()
  await create.getByRole('status').filter({hasText:'账号已创建，请提醒用户登录后修改初始密码、按需绑定邮箱'}).waitFor()
  await create.getByRole('alert').filter({hasText:'数据刷新失败'}).waitFor()
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
  await own.getByRole('navigation', {name:'管理员后台导航'}).getByRole('button', {name:'账号安全', exact:true}).click()
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
  await own.close()

  const rag = await mount()
  const nav = rag.getByRole('navigation', {name:'管理员后台导航'})
  await nav.getByRole('button', {name:'模型与检索', exact:true}).click()
  await rag.locator('#embedding-model').fill('draft-embedding')
  const leave = nav.getByRole('button', {name:'平台概览', exact:true})
  let dialog = rag.waitForEvent('dialog')
  let click = leave.click()
  await (await dialog).dismiss()
  await click
  assert.equal(await rag.locator('#embedding-model').inputValue(), 'draft-embedding')
  assert.equal(await rag.evaluate(() => !window.dispatchEvent(new Event('beforeunload', {cancelable:true}))), true)
  dialog = rag.waitForEvent('dialog')
  click = leave.click()
  await (await dialog).accept()
  await click
  await nav.getByRole('button', {name:'模型与检索', exact:true}).click()
  await rag.locator('#embedding-model').waitFor()
  assert.equal(await rag.locator('#embedding-model').inputValue(), 'fake-embedding')
  await rag.locator('#rerank-model').fill('updated-rerank')
  await rag.getByRole('button', {name:'保存配置', exact:true}).click()
  await rag.waitForFunction(() => Boolean(window.adminHarness.ragSave))
  assert.equal(await leave.isDisabled(), true)
  assert.equal(await rag.getByRole('button', {name:'退出登录', exact:true}).isDisabled(), true)
  assert.equal(await rag.evaluate(() => !window.dispatchEvent(new Event('beforeunload', {cancelable:true}))), true)
  await rag.evaluate(() => {
    const h = window.adminHarness;
    h.rag = {...h.rag, active:{...h.rag.active, rerank_model:h.ragSave.body.rerank_model}, revision:2};
    h.ragSave.resolve(h.rag);
  })
  await rag.getByRole('status').filter({hasText:'配置已保存，将用于后续请求'}).waitFor()
  assert.equal(await leave.isEnabled(), true)
  assert.equal(await rag.evaluate(() => !window.dispatchEvent(new Event('beforeunload', {cancelable:true}))), false)
  await leave.click()
  await rag.close()
  for (const [failure, message] of [
    [404, '当前后端未提供模型与检索接口'],
    [503, '后端或数据服务暂不可用'],
    ['network', '无法连接后端'],
  ]) {
    const failed = await mount()
    await failed.evaluate(value => { window.adminHarness.ragFailure = value }, failure)
    await failed.getByRole('navigation', {name:'管理员后台导航'}).getByRole('button', {name:'模型与检索', exact:true}).click()
    await failed.getByRole('alert').filter({hasText:message}).waitFor()
    await failed.evaluate(() => { window.adminHarness.ragFailure = null })
    await failed.getByRole('button', {name:'刷新状态', exact:true}).click()
    await failed.locator('#embedding-model').waitFor()
    assert.equal(await failed.locator('#embedding-model').inputValue(), 'fake-embedding')
    await failed.close()
  }
  console.log('PASS: admin RAG distinguishes old-backend 404, service failure and network loss; refresh recovers')
  assert.deepEqual(errors, [])
  console.log('PASS: latest search, persistent totals, real Toast feedback, self revocation, own-password reminder, dirty navigation and saving guards')
} finally {
  await browser.close()
}
