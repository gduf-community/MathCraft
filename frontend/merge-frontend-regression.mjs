/* global URL, console, process, window, Event, File, Response, AbortSignal */
/** 主线整合风险回归：真实 React/题库适配层，内存假服务，浏览器所有网络均阻断。 */
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'

const require = createRequire(join(tmpdir(), 'mathcraft-auth-browser', 'package.json'))
const { chromium } = require('playwright-core')
const backend = await readFile(new URL('./src/api/backend.ts', import.meta.url), 'utf8')
const exports = [...backend.matchAll(/export (async )?function (\w+)/g)]
const stubs = {
  backend: `export {ApiError, request, setApiToken} from './session';\n` + exports.map(([, asyncKeyword, name]) => `export const ${name} = ${asyncKeyword ?? ''}(...args) => window.mergeHarness.backend.${name}(...args);`).join('\n'),
  session: `
    export class ApiError extends Error {
      constructor(message, code = 'REQUEST_FAILED', status = 0) { super(message); this.code = code; this.status = status; }
    }
    export const request = (...args) => window.mergeHarness.backend.request(...args);
    export const setApiToken = token => { window.mergeHarness.token = token; };
    export const sessionFetch = (...args) => window.mergeHarness.sessionFetch(...args);
    export const getSessionGeneration = () => window.mergeHarness.generation;
    export const onSessionCleared = listener => {
      window.mergeHarness.listeners.add(listener);
      return () => window.mergeHarness.listeners.delete(listener);
    };
    export const assertCurrentSession = started => {
      if (started !== getSessionGeneration()) throw new ApiError('synthetic session ended', 'SESSION_ENDED', 401);
    };
  `,
  AuthContext: `export const useAuth = () => ({user: window.mergeHarness.user, logout: async () => {}});`,
}
const bundle = await build({
  stdin: { contents: `
    import React, {useEffect} from 'react';
    import {createRoot} from 'react-dom/client';
    import {AppProvider, useApp} from './src/store/AppContext';
    import {ToastProvider} from './src/store/ToastContext';
    import Toast from './src/components/ui/Toast';
    import {SettingsPage} from './src/components/settings/SettingsPage';
    import BankCreateModal from './src/components/tabs/BankTab/BankCreateModal';
    import BankEditModal from './src/components/tabs/BankTab/BankEditModal';
    import BankViewModal from './src/components/tabs/BankTab/BankViewModal';
    import TopBar from './src/components/layout/TopBar';
    import ChatInput from './src/components/tabs/GenerateTab/ChatInput';
    function Harness() {
      const app = useApp(), h = window.mergeHarness;
      useEffect(() => { window.mergeApp = app; }, [app]);
      const callbacks = {onClose: () => h.closed++, onChanged: deletedId => {
        h.changed++;
        h.changedDocumentIds.push(deletedId ?? null);
        // 与 BankTab 的实际父回调保持顺序：先精确失效，再异步刷新。
        if (deletedId) app.invalidateDocument(h.bank.id, deletedId);
        void app.refreshKbs().then(() => { h.changeRefreshesFinished++; });
      }};
      return <>
        <TopBar/>
        {h.mode === 'settings' && <>
          <button onClick={() => app.setActiveTab('settings')}>打开个人设置</button>
          <button onClick={() => app.setActiveTab('preview')}>离开个人设置</button>
          {app.activeTab === 'settings' && <SettingsPage/>}
        </>}
        {h.mode === 'create' && <BankCreateModal {...callbacks}/>}
        {h.mode === 'edit' && <BankEditModal bank={h.bank} {...callbacks}/>}
        {h.mode === 'view' && <BankViewModal bank={h.bank} {...callbacks}/>}
        <ChatInput/>
        <output data-testid="kbs">{JSON.stringify(app.kbs)}</output>
        <output data-testid="selection">{JSON.stringify({bank:app.selectedKbId, document:app.selectedDocId})}</output>
        <output data-testid="docs">{JSON.stringify(app.docs)}</output>
        <output data-testid="messages">{JSON.stringify(app.messages)}</output>
      </>;
    }
    const root = createRoot(document.getElementById('root'));
    window.unmountMerge = () => root.unmount();
    window.remountMerge = () => root.render(<ToastProvider key={window.mergeHarness.generation}><AppProvider><Harness/></AppProvider><Toast/></ToastProvider>);
    window.remountMerge();
  `, resolveDir: fileURLToPath(new URL('.', import.meta.url)), loader: 'jsx' },
  bundle: true, write: false, format: 'iife', jsx: 'automatic',
  plugins: [{ name: 'synthetic-merge-boundaries', setup(builder) {
    builder.onResolve({ filter: /\/(backend|session|AuthContext)$/ }, args => ({
      path: args.path.split('/').at(-1), namespace: 'merge-fakes',
    }))
    builder.onLoad({ filter: /.*/, namespace: 'merge-fakes' }, args => ({ contents: stubs[args.path] }))
  } }],
})
const browser = await chromium.launch({ executablePath: process.env.AUTH_BROWSER ?? join(
  homedir(), 'AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe',
), headless: true })
const errors = []
const failures = []
let passed = 0
function pass(message) { passed++; console.log('PASS:', message) }
async function mount(mode, role = 'teacher', memberRole = 'creator', format = 'TXT') {
  const page = await browser.newPage()
  page.setDefaultTimeout(15000)
  await page.route('**/*', route => route.abort())
  page.on('pageerror', error => errors.push(error.message))
  await page.setContent('<div id="root"></div>')
  await page.evaluate(({ mode, role, memberRole, format }) => {
    const h = window.mergeHarness = { mode, generation: 0, closed: 0, changed: 0,
      changedDocumentIds: [], changeRefreshesFinished: 0,
      calls: [], timers: new Map(), timerId: 0, listeners:new Set(),
      user: {userId:'A', username:'fake-A', displayName:'合成用户', role, emailVerified:false},
      notifications: [], held: {}, pending: {}, documents: {}, preview: '# 远端文档预览\n\n**原样文本** $x$',
    }
    window.setInterval = (action, delay) => { const id = ++h.timerId; h.timers.set(id, {action, delay}); return id }
    window.clearInterval = id => h.timers.delete(id)
    h.tick = delay => { for (const timer of [...h.timers.values()]) if (timer.delay === delay) timer.action() }
    h.doc = id => ({id:'doc-' + id, bank_id:id, name:id + '.txt', format:'TXT', size_bytes:12,
      status:'ready', progress:100, is_scanned:false, chunk_count:1, created_at:'2026-11-10'})
    h.sessionFetch = async (path, init) => {
      h.calls.push({name:'sessionFetch', args:[path, init]})
      init?.signal?.throwIfAborted()
      return new Response(h.pdfBody ?? '%PDF-1.4\n%%EOF', {status:h.pdfStatus ?? 200,
        headers:{'Content-Type':h.pdfType ?? 'application/pdf'}})
    }
    h.invalidate = () => { h.generation++; for (const listener of [...h.listeners]) listener() }
    h.apiBank = {id:'bank-A', name:'合成题库', code:'fake-code', creator:{id:'A', display_name:'合成用户'},
      member_count:1, capacity:100, source:'owned', quitted:false, my_role:memberRole,
      can_upload_document:memberRole !== 'readonly', can_download_document:true,
      can_delete_document:memberRole !== 'readonly', can_manage_members:memberRole === 'creator',
      can_edit_bank:memberRole === 'creator', can_transfer_bank:false, can_delete_bank:memberRole === 'creator'}
    h.bank = {id:'bank-A', name:'合成题库', code:'fake-code', creator:'合成用户',
      memberCount:1, capacity:100, source:'owned', myRole:memberRole,
      canUpload:memberRole !== 'readonly', canDownload:true, canDeleteDoc:memberRole !== 'readonly',
      canManageMembers:memberRole === 'creator', canEdit:memberRole === 'creator', canDelete:memberRole === 'creator',
      docs:[{id:'doc-bank-A', name:'bank-A.' + format.toLowerCase(), format, size:'12 B', status:'parsing', stage:'正在解析', progress:25}],
      members:[{id:'member-A', userId:'A', name:'合成用户', role:memberRole, isMe:true, isCreator:memberRole === 'creator'}]}
    const defaults = {
      listBanks: () => h.banks ?? [h.apiBank], latestBatch: () => ({batch_id:null, questions:[]}),
      getModelSettings: () => ({deepseek_model:'fake-deepseek', deepseek_key_configured:false,
        deepseek_key_masked:null, mineru_token_configured:false, mineru_token_masked:null,
        mineru_limits:{max_file_mb:100, max_pages:200}, embedding_model:'fake-embedding', rerank_model:'fake-rerank'}),
      saveModelSettings: () => {},
      listFavoriteGroups: () => [], listFavorites: () => [], listPapers: () => [], listSpaces: () => [],
      listNotifications: () => ({items:h.notifications, unread_count:h.notifications.length}),
      listDocuments: id => h.documents[id] ?? [h.doc(id)], listBankMembers: () => [],
      getDocument: (bankId, docId) => ({...h.doc(bankId), id:docId, name:h.uploadName ?? 'same.txt'}),
      deleteDocument: (bankId, docId) => {
        h.documents[bankId] = (h.documents[bankId] ?? [h.doc(bankId)]).filter(doc => doc.id !== docId)
      },
      mapBankToKnowledgeBase: bank => ({id:bank.id, name:bank.name}),
      mapDocument: doc => ({id:doc.id, kbId:doc.bank_id, name:doc.name,
        status:doc.status, stage:doc.stage, progress:doc.progress, api:doc}),
      mapQuestion: question => question, formatFileSize: bytes => bytes + ' B',
      fetchDocumentText: () => { if (h.previewError) throw new Error(h.previewError); return h.preview },
      downloadDocument: () => {}, openPdfDocument: () => {}, viewDocument: () => {},
      createBankWithDocument: () => ({bank:h.apiBank, document:{name:'synthetic.txt', eta_minutes:1}}),
      uploadDocument: () => ({document_id:'doc-new', status:'uploaded', stage:'queued', progress:0}),
      getBank: () => h.apiBank, createBank: () => h.apiBank,
      createChatSession: () => ({session_id:'session-A'}),
      sendChatMessage: () => ({reply:'当前对话结果', questions:[]}),
      getChatProgress: () => ({active:true, percent:20, stage:'合成进度'}), cancelChat: () => {},
      startGeneration: () => ({task_id:'fake-task'}),
      getGenerationProgress: () => ({done:false, progress:10, stage:'生成中'}),
      clearUrgeBadge: () => {}, markNotificationsRead: () => {},
    }
    h.backend = new Proxy({}, {get: (target, name) => (...args) => {
      h.calls.push({name, args})
      if (h.held[name]) return new Promise((resolve, reject) => {
        ;(h.pending[name] ??= []).push({args, resolve, reject})
      })
      if (name in target) return target[name](...args)
      if (!(name in defaults)) throw new Error('unexpected API: ' + String(name))
      return defaults[name](...args)
    }})
    h.finish = (name, value, bankId) => {
      const index = bankId === undefined ? 0 : h.pending[name].findIndex(item => item.args[0] === bankId)
      if (index < 0) throw new Error('No pending ' + name + ' for ' + bankId)
      h.pending[name].splice(index, 1)[0].resolve(value)
    }
  }, {mode, role, memberRole, format})
  await page.addScriptTag({ content: bundle.outputFiles[0].text })
  await page.waitForFunction(() => window.mergeApp && window.mergeHarness.calls.some(call => call.name === 'listSpaces'))
  return page
}
async function attachFiles(page) {
  await page.locator('input[type=file]').setInputFiles({name:'one.txt', mimeType:'text/plain', buffer:Buffer.from('synthetic document')})
  // 原组件一次选择一个文件，使用两次选择验证后台队列。
  await page.locator('input[type=file]').setInputFiles({name:'two.txt', mimeType:'text/plain', buffer:Buffer.from('synthetic document')})
}
async function providerCase(name, run) {
  const page = await mount('context')
  try { await run(page); pass(name) }
  catch (error) { failures.push({name, message:error.message}); console.error('FAIL:', name, '\n ', error.message) }
  finally { await page.close() }
}
async function selectBank(page, id = 'bank-A') {
  await page.evaluate(id => window.mergeApp.selectKb(id), id)
  await page.waitForFunction(id => window.mergeApp.selectedKbId === id && window.mergeApp.docs[0]?.kbId === id, id)
}
async function settleRender(page) {
  // 等 React 提交已完成请求的状态，避免在旧状态尚未提交时误判隔离成功。
  await page.evaluate(() => new Promise(resolve => window.requestAnimationFrame(() => window.requestAnimationFrame(resolve))))
}
try {
  const settings = await mount('settings')
  await settings.getByRole('button', {name:'打开个人设置', exact:true}).click()
  const key = settings.getByLabel('新的 DeepSeek API Key', {exact:true})
  await key.fill('synthetic-draft-key')
  await settings.waitForFunction(() => window.mergeApp.hasUnsavedChanges)
  const leaveSettings = settings.getByRole('button', {name:'离开个人设置', exact:true})
  let dialog = settings.waitForEvent('dialog')
  let click = leaveSettings.click()
  await (await dialog).dismiss()
  await click
  assert.equal(await key.inputValue(), 'synthetic-draft-key')
  assert.equal(await settings.evaluate(() => !window.dispatchEvent(new Event('beforeunload', {cancelable:true}))), true)
  dialog = settings.waitForEvent('dialog')
  click = leaveSettings.click()
  await (await dialog).accept()
  await click
  await settings.waitForFunction(() => window.mergeApp.activeTab === 'preview' && !window.mergeApp.hasUnsavedChanges)
  await settings.getByRole('button', {name:'打开个人设置', exact:true}).click()
  await key.waitFor()
  assert.equal(await key.inputValue(), '')
  await key.fill('synthetic-saved-key')
  await settings.evaluate(() => { window.mergeHarness.held.saveModelSettings = true })
  await settings.getByRole('button', {name:'保存配置', exact:true}).click()
  await settings.waitForFunction(() => window.mergeHarness.pending.saveModelSettings?.length === 1)
  await leaveSettings.click()
  assert.equal(await settings.evaluate(() => window.mergeApp.activeTab), 'settings')
  assert.equal(await settings.evaluate(() => window.mergeApp.isSettingsSaving), true)
  await settings.getByRole('alert').filter({hasText:'配置正在保存，请等待完成后再离开'}).waitFor()
  await settings.evaluate(() => {
    const h = window.mergeHarness; h.held.getModelSettings = true; h.finish('saveModelSettings');
  })
  await settings.waitForFunction(() => window.mergeHarness.pending.getModelSettings?.length === 1)
  assert.equal(await key.inputValue(), '')
  assert.equal(await settings.evaluate(() => !window.dispatchEvent(new Event('beforeunload', {cancelable:true}))), true)
  await leaveSettings.click()
  assert.equal(await settings.evaluate(() => window.mergeApp.activeTab), 'settings')
  await settings.evaluate(() => {
    const h = window.mergeHarness; h.held.getModelSettings = false;
    h.finish('getModelSettings', {deepseek_model:'fake-deepseek', deepseek_key_configured:true,
      deepseek_key_masked:'***', mineru_token_configured:false, mineru_token_masked:null,
      mineru_limits:{max_file_mb:100, max_pages:200}, embedding_model:'fake-embedding', rerank_model:'fake-rerank'});
  })
  await settings.getByRole('status').filter({hasText:'模型配置已保存。现在可以测试已保存的配置。'}).last().waitFor()
  await settings.waitForFunction(() => !window.mergeApp.isSettingsSaving && !window.mergeApp.hasUnsavedChanges)
  assert.equal(await settings.evaluate(() => !window.dispatchEvent(new Event('beforeunload', {cancelable:true}))), false)
  await leaveSettings.click()
  await settings.waitForFunction(() => window.mergeApp.activeTab === 'preview')
  await settings.close()
  pass('personal settings keep cancelled drafts, confirm discard, block navigation and refresh throughout save/readback, retain real Toast feedback')

  const student = await mount('create', 'student')
  assert.equal(await student.getByRole('heading', {name:'新建题库', exact:true}).count(), 0)
  await student.close()

  for (const fail of [false, true]) {
    const create = await mount('create')
    await attachFiles(create)
    await create.getByLabel('题库名称', {exact:true}).fill('保留的题库草稿')
    if (fail) await create.evaluate(() => {
      window.mergeHarness.backend.createBankWithDocument = () => { throw new Error('synthetic creation failure') }
    })
    await create.getByRole('button', {name:'创建', exact:true}).click()
    if (fail) {
      await create.getByRole('alert').filter({hasText:'synthetic creation failure'}).first().waitFor()
      assert.equal(await create.evaluate(() => window.mergeHarness.closed), 0, '首个文件失败必须保留弹窗草稿')
      assert.equal(await create.getByLabel('题库名称', {exact:true}).inputValue(), '保留的题库草稿')
      assert.equal(await create.getByRole('button', {name:'移除one.txt', exact:true}).count(), 1)
      assert.equal(await create.getByRole('button', {name:'移除two.txt', exact:true}).count(), 1)
      await create.evaluate(() => {
        const h = window.mergeHarness
        h.backend.createBankWithDocument = () => ({bank:h.apiBank, document:{name:'one.txt', eta_minutes:1}})
      })
      await create.getByRole('button', {name:'创建', exact:true}).click()
    }
    await create.waitForFunction(() => window.mergeHarness.closed === 1)
    const uploads = await create.evaluate(() => window.mergeHarness.calls.filter(call => call.name === 'uploadDocument'))
    assert.equal(uploads.length, 1)
    assert.equal(uploads[0].args[0], 'bank-A')
    await create.close()
  }
  const staleCreate = await mount('create')
  await attachFiles(staleCreate)
  await staleCreate.evaluate(() => { window.mergeHarness.held.createBankWithDocument = true })
  await staleCreate.getByRole('button', {name:'创建', exact:true}).click()
  await staleCreate.waitForFunction(() => window.mergeHarness.pending.createBankWithDocument?.length === 1)
  await staleCreate.evaluate(() => {
    const h = window.mergeHarness; h.generation++
    h.finish('createBankWithDocument', {bank:h.apiBank, document:{name:'synthetic.txt', eta_minutes:1}})
  })
  await staleCreate.waitForFunction(() => window.mergeHarness.pending.createBankWithDocument.length === 0)
  assert.equal(await staleCreate.evaluate(() => window.mergeHarness.calls.filter(call => call.name === 'uploadDocument').length), 0)
  await staleCreate.close()
  pass('teacher-only creation, failed creation retains name/files for retry, queue resumes, changed session stops follow-up writes')

  for (const memberRole of ['creator', 'editor', 'readonly']) {
    const view = await mount(memberRole === 'creator' ? 'edit' : 'view', 'teacher', memberRole)
    assert.equal(await view.getByLabel('成员登录账号').count(), memberRole === 'creator' ? 1 : 0)
    assert.equal(await view.getByTitle('删除文档').count(), memberRole === 'readonly' ? 0 : 1)
    assert.equal(await view.locator('input[type=file]').count(), memberRole === 'readonly' ? 0 : 1)
    await view.getByText('正在解析 25%', {exact:true}).waitFor()
    await view.getByTitle('查看文档').click()
    await view.getByText('# 远端文档预览', {exact:false}).waitFor()
    assert.equal(await view.getByRole('heading', {name:'远端文档预览', exact:true}).count(), 0, 'TXT 不应解析为 Markdown 标题')
    assert.equal(await view.locator('.katex').count(), 0, 'TXT 不应渲染公式')
    const textCall = await view.evaluate(() => window.mergeHarness.calls.find(call => call.name === 'fetchDocumentText'))
    assert.equal(textCall.args[3], 'TXT', '入口应传递实际文档格式')
    assert.equal(await view.evaluate(() => window.mergeHarness.calls.find(call => call.name === 'fetchDocumentText').args[2] instanceof AbortSignal), true)
    await view.getByLabel('关闭文档预览').click()
    assert.equal(await view.evaluate(() => window.mergeHarness.closed), 0, '关闭预览不得关闭父弹窗')
    await view.evaluate(() => { window.mergeHarness.preview = '' })
    await view.getByTitle('查看文档').click()
    await view.getByText('文档暂无可预览内容', {exact:true}).waitFor()
    await view.getByRole('dialog', {name:'文档预览：bank-A.txt', exact:true}).dispatchEvent('click')
    assert.equal(await view.evaluate(() => window.mergeHarness.closed), 0)
    await view.evaluate(() => { window.mergeHarness.previewError = 'synthetic preview failure' })
    await view.getByTitle('查看文档').click()
    await view.getByRole('alert').filter({hasText:'synthetic preview failure'}).waitFor()
    await view.close()
  }
  pass('creator/editor/readonly capabilities, TXT remains plain text with signal/format, preview success/empty/error and independent close')

  for (const mode of ['edit', 'view']) {
    for (const format of ['MD', 'PDF', 'DOCX', 'XLSX']) {
      const view = await mount(mode, 'teacher', mode === 'edit' ? 'creator' : 'editor', format)
      if (format === 'PDF') {
        const opened = view.waitForEvent('popup')
        await view.getByTitle('查看文档').click()
        const popup = await opened
        await popup.getByRole('status').filter({hasText:'PDF 已载入'}).waitFor()
        assert.equal(await popup.locator('iframe').getAttribute('src').then(src => src.startsWith('blob:')), true)
        assert.equal(await view.evaluate(() => window.mergeHarness.calls.some(call => call.name === 'fetchDocumentText')), false)
        assert.equal(await view.evaluate(() => window.mergeHarness.calls.find(call => call.name === 'sessionFetch').args[1].signal instanceof AbortSignal), true)
        await popup.close()
        await view.evaluate(() => window.mergeHarness.tick(250))
      } else if (format === 'MD') {
        await view.getByTitle('查看文档').click()
        await view.getByRole('heading', {name:'远端文档预览', exact:true}).waitFor()
        assert.equal(await view.locator('.katex').count(), 1)
        await view.getByLabel('关闭文档预览').click()
      } else {
        await view.getByTitle('查看文档').click()
        await view.getByRole('status').filter({hasText:`${format} 暂不支持内联预览，请使用下载按钮`}).waitFor()
        assert.equal(await view.getByRole('dialog', {name:/文档预览/}).count(), 0)
        assert.equal(await view.evaluate(() => window.mergeHarness.calls.some(call => ['fetchDocumentText', 'sessionFetch'].includes(call.name))), false)
      }
      assert.equal(await view.evaluate(() => window.mergeHarness.closed), 0)
      await view.close()
    }
  }
  pass('edit/view dispatch MD to rich preview, PDF to authenticated Blob helper, DOCX/XLSX to download guidance')

  await providerCase('invalidateDocument clears selection/cache while listBanks is held and keeps deleted rows absent after refresh', async page => {
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.documents['bank-A'] = [h.doc('bank-A'), {...h.doc('bank-A'), id:'keep-id', name:'keep.txt'}]
    })
    await selectBank(page)
    await page.evaluate(() => window.mergeApp.selectDoc('doc-bank-A'))
    await page.waitForFunction(() => window.mergeApp.selectedDocId === 'doc-bank-A')
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.held.listBanks = true
      h.refreshDone = false
      void window.mergeApp.refreshKbs().then(() => { h.refreshDone = true })
    })
    await page.waitForFunction(() => window.mergeHarness.pending.listBanks?.length === 1)
    const documentLoadsBefore = await page.evaluate(() => window.mergeHarness.calls.filter(call => call.name === 'listDocuments').length)
    await page.evaluate(() => window.mergeApp.invalidateDocument('bank-A', 'doc-bank-A'))
    await settleRender(page)
    assert.deepEqual(await page.evaluate(() => window.mergeApp.docs.map(doc => doc.id)), ['keep-id'], '只移除已删除文档，保留其余缓存')
    assert.equal(await page.evaluate(() => window.mergeApp.selectedDocId), '', '不能等待题库刷新后才清空选择')
    assert.equal(await page.evaluate(() => window.mergeApp.selectedKbId), 'bank-A')
    assert.equal(await page.evaluate(() => window.mergeHarness.pending.listBanks.length), 1, '验证清理时 listBanks 仍未返回')
    assert.equal(await page.evaluate(() => window.mergeHarness.refreshDone), false)
    assert.deepEqual(JSON.parse(await page.getByTestId('selection').textContent()), {bank:'bank-A', document:''})
    await page.evaluate(() => {
      const h = window.mergeHarness
      // 删除已在服务端完成；banks 返回后启动的是新的文档请求。
      h.documents['bank-A'] = h.documents['bank-A'].filter(doc => doc.id !== 'doc-bank-A')
      h.finish('listBanks', [h.apiBank])
    })
    await page.waitForFunction(() => window.mergeHarness.refreshDone)
    await settleRender(page)
    assert.deepEqual(await page.evaluate(() => window.mergeApp.docs.map(doc => doc.id)), ['keep-id'])
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.filter(call => call.name === 'listDocuments').length), documentLoadsBefore + 1,
      '题库列表有效返回后，应以新版本请求当前库文档；即时清理不依赖该请求')
    await page.evaluate(() => window.mergeApp.selectDoc('keep-id'))
    await page.waitForFunction(() => window.mergeApp.selectedDocId === 'keep-id')
    await page.evaluate(() => window.mergeApp.invalidateDocument('bank-B', 'keep-id'))
    await settleRender(page)
    assert.equal(await page.evaluate(() => window.mergeApp.selectedDocId), 'keep-id', '其他题库的删除不能影响当前选择')
    assert.deepEqual(await page.evaluate(() => window.mergeApp.docs.map(doc => doc.id)), ['keep-id'])
  })

  await providerCase('invalidateDocument alone prevents an already in-flight listDocuments from restoring a deleted item', async page => {
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.documents['bank-A'] = [h.doc('bank-A'), {...h.doc('bank-A'), id:'keep-id', name:'keep.txt'}]
    })
    await selectBank(page)
    await page.evaluate(() => window.mergeApp.selectDoc('doc-bank-A'))
    await page.waitForFunction(() => window.mergeApp.selectedDocId === 'doc-bank-A')
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.held.listDocuments = true
      h.refreshDone = false
      void window.mergeApp.refreshKbs().then(() => { h.refreshDone = true })
    })
    await page.waitForFunction(() => window.mergeHarness.pending.listDocuments?.length === 1)
    // 不再调用 refreshKbs/selectKb，单独验证精确失效本身能阻止旧响应写回。
    await page.evaluate(() => window.mergeApp.invalidateDocument('bank-A', 'doc-bank-A'))
    await settleRender(page)
    assert.deepEqual(await page.evaluate(() => window.mergeApp.docs.map(doc => doc.id)), ['keep-id'])
    assert.equal(await page.evaluate(() => window.mergeApp.selectedDocId), '')
    await page.evaluate(() => { const h = window.mergeHarness; h.finish('listDocuments', h.documents['bank-A']) })
    await page.waitForFunction(() => window.mergeHarness.refreshDone)
    await settleRender(page)
    assert.deepEqual(await page.evaluate(() => window.mergeApp.docs.map(doc => doc.id)), ['keep-id'], '旧列表不能复活已删除的文档')
    assert.equal(await page.evaluate(() => window.mergeApp.selectedDocId), '')
  })

  for (const mode of ['edit', 'view']) {
    const deletion = await mount(mode, 'teacher', mode === 'edit' ? 'creator' : 'editor')
    try {
      await selectBank(deletion)
      await deletion.evaluate(() => window.mergeApp.selectDoc('doc-bank-A'))
      await deletion.waitForFunction(() => window.mergeApp.selectedDocId === 'doc-bank-A')
      await deletion.evaluate(() => {
        const h = window.mergeHarness
        h.held.listDocuments = true
        void window.mergeApp.refreshKbs()
      })
      await deletion.waitForFunction(() => window.mergeHarness.pending.listDocuments?.length === 1)
      await deletion.evaluate(() => {
        const h = window.mergeHarness
        h.held.listBanks = h.held.deleteDocument = true
      })
      await deletion.getByTitle('删除文档').click()
      await deletion.waitForFunction(() => window.mergeHarness.pending.deleteDocument?.length === 1)
      assert.equal(await deletion.evaluate(() => window.mergeApp.selectedDocId), 'doc-bank-A', '删除尚未完成时不能提前清空')
      assert.equal(await deletion.evaluate(() => window.mergeHarness.changed), 0, '仅在删除完成后通知父组件')
      assert.deepEqual(await deletion.evaluate(() => window.mergeHarness.pending.deleteDocument[0].args), ['bank-A', 'doc-bank-A'])
      await deletion.evaluate(() => {
        const h = window.mergeHarness
        h.documents['bank-A'] = []
        h.finish('deleteDocument')
      })
      await deletion.waitForFunction(() => window.mergeHarness.pending.listBanks?.length === 1 && window.mergeHarness.changed === 1)
      await settleRender(deletion)
      assert.deepEqual(await deletion.evaluate(() => window.mergeHarness.changedDocumentIds), ['doc-bank-A'], '弹窗必须传出实际删除的 ID')
      assert.deepEqual(await deletion.evaluate(() => window.mergeApp.docs), [])
      assert.equal(await deletion.evaluate(() => window.mergeApp.selectedDocId), '')
      assert.equal(await deletion.getByTitle('删除文档').count(), 0, '弹窗本地列表也应立即移除文档')
      assert.equal(await deletion.evaluate(() => window.mergeHarness.changeRefreshesFinished), 0, '清理不能依赖刷新完成')
      await deletion.evaluate(() => {
        const h = window.mergeHarness
        h.finish('listDocuments', [h.doc('bank-A')])
      })
      await settleRender(deletion)
      assert.deepEqual(await deletion.evaluate(() => window.mergeApp.docs), [], '删除前的旧列表不能写回已删除项')
      assert.equal(await deletion.evaluate(() => window.mergeApp.selectedDocId), '')
      assert.equal(await deletion.evaluate(() => window.mergeHarness.pending.listBanks.length), 1)
      await deletion.evaluate(() => {
        const h = window.mergeHarness
        h.held.listDocuments = false
        h.finish('listBanks', [h.apiBank])
      })
      await deletion.waitForFunction(() => window.mergeHarness.changeRefreshesFinished === 1)
      await settleRender(deletion)
      assert.deepEqual(await deletion.evaluate(() => window.mergeApp.docs), [])
      assert.equal(await deletion.evaluate(() => window.mergeApp.selectedDocId), '')
      pass(`${mode} modal passes deleted ID and clears AppProvider immediately before its held refresh; stale rows stay invalid`)
    } catch (error) {
      failures.push({name:`${mode} modal immediate deletion invalidation`, message:error.message})
      console.error('FAIL:', mode, 'modal immediate deletion invalidation\n ', error.message)
    } finally { await deletion.close() }
  }

  await providerCase('refreshKbs clears deleted document cache and selection without waiting for polling', async page => {
    await selectBank(page)
    await page.evaluate(() => window.mergeApp.selectDoc('doc-bank-A'))
    await page.waitForFunction(() => window.mergeApp.selectedDocId === 'doc-bank-A')
    await page.evaluate(() => window.mergeApp.refreshKbs())
    assert.equal(await page.evaluate(() => window.mergeApp.selectedDocId), 'doc-bank-A', '仍存在的文档应保持选择')
    await page.evaluate(() => {
      window.mergeHarness.documents['bank-A'] = []
      return window.mergeApp.refreshKbs()
    })
    await page.waitForFunction(() => window.mergeApp.docs.length === 0 && window.mergeApp.selectedDocId === '')
    assert.equal(await page.evaluate(() => window.mergeApp.selectedKbId), 'bank-A')
    assert.deepEqual(JSON.parse(await page.getByTestId('docs').textContent()), [])
    await page.evaluate(() => window.mergeApp.selectKb('bank-A'))
    await page.waitForFunction(() => window.mergeApp.docs.length === 0 && window.mergeApp.selectedDocId === '')
  })

  await providerCase('refreshKbs clears selected bank, docs and selection when the bank is deleted', async page => {
    await selectBank(page)
    await page.evaluate(() => window.mergeApp.selectDoc('doc-bank-A'))
    await page.waitForFunction(() => window.mergeApp.selectedDocId === 'doc-bank-A')
    const before = await page.evaluate(() => window.mergeHarness.calls.filter(call => call.name === 'listDocuments').length)
    await page.evaluate(() => {
      window.mergeHarness.banks = []
      return window.mergeApp.refreshKbs()
    })
    await page.waitForFunction(() => window.mergeApp.kbs.length === 0 && window.mergeApp.docs.length === 0
      && window.mergeApp.selectedKbId === '' && window.mergeApp.selectedDocId === '')
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.filter(call => call.name === 'listDocuments').length), before,
      '题库已删除时不能再请求它的文档')
  })

  await providerCase('uploadAndWait selects returned document ID when names collide', async page => {
    await selectBank(page)
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.uploadName = 'same.txt'
      h.documents['bank-A'] = [{...h.doc('bank-A'), id:'old-id', name:'same.txt'},
        {...h.doc('bank-A'), id:'doc-new', name:'same.txt'}]
      return window.mergeApp.uploadDocument(new File(['synthetic'], 'same.txt', {type:'text/plain'}))
    })
    await page.waitForFunction(() => window.mergeApp.selectedDocId === 'doc-new')
    assert.deepEqual(await page.evaluate(() => window.mergeApp.docs.map(doc => doc.id)), ['old-id', 'doc-new'])
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.find(call => call.name === 'getDocument').args[1]), 'doc-new')
  })

  await providerCase('notification refresh preserves the uploaded ID selection after superseding its document request', async page => {
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.documents['bank-A'] = [{...h.doc('bank-A'), id:'old-id', name:'same.txt'}]
    })
    await selectBank(page)
    await page.evaluate(() => window.mergeApp.selectDoc('old-id'))
    await page.waitForFunction(() => window.mergeApp.selectedDocId === 'old-id')
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.held.listDocuments = true
      h.uploadDone = false
      void window.mergeApp.uploadDocument(new File(['synthetic'], 'same.txt', {type:'text/plain'}))
        .then(() => { h.uploadDone = true })
    })
    await page.waitForFunction(() => window.mergeHarness.pending.listDocuments?.length === 1)
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.find(call => call.name === 'getDocument').args[1]), 'doc-new')
    await page.getByRole('status').filter({hasText:'「same.txt」已上传并入库'}).waitFor()
    assert.equal(await page.evaluate(() => window.mergeHarness.uploadDone), false, '入库成功提示不应等待列表响应')
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.notifications = [{id:'uploaded-ready', bank_id:'bank-A'}]
      h.tick(10000)
    })
    await page.waitForFunction(() => window.mergeHarness.pending.listDocuments.length === 2)
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.documents['bank-A'] = [{...h.doc('bank-A'), id:'old-id', name:'same.txt'},
        {...h.doc('bank-A'), id:'doc-new', name:'same.txt'}]
      // 后发通知刷新先返回；原上传请求仍挂起，选择意图必须由有效刷新消费。
      h.pending.listDocuments.splice(1, 1)[0].resolve(h.documents['bank-A'])
    })
    await page.waitForFunction(() => window.mergeApp.docs.some(doc => doc.id === 'doc-new'))
    assert.equal(await page.evaluate(() => window.mergeHarness.uploadDone), false)
    await page.evaluate(() => { const h = window.mergeHarness; h.finish('listDocuments', h.documents['bank-A']) })
    await page.waitForFunction(() => window.mergeHarness.uploadDone)
    await settleRender(page)
    assert.deepEqual(await page.evaluate(() => window.mergeApp.docs.map(doc => doc.id)), ['old-id', 'doc-new'])
    assert.equal(await page.evaluate(() => window.mergeApp.selectedKbId), 'bank-A')
    assert.equal(await page.evaluate(() => window.mergeApp.selectedDocId), 'doc-new',
      '通知刷新覆盖上传的文档请求后，仍必须按上传返回 ID 选择新文档')
  })

  await providerCase('bank list refresh survives a bank switch while its stale document work cannot replace B', async page => {
    await selectBank(page)
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.held.listBanks = true
      h.refreshDone = false
      void window.mergeApp.refreshKbs().then(() => { h.refreshDone = true })
    })
    await page.waitForFunction(() => window.mergeHarness.pending.listBanks?.length === 1)
    await selectBank(page, 'bank-B')
    await page.evaluate(() => window.mergeApp.selectDoc('doc-bank-B'))
    await page.waitForFunction(() => window.mergeApp.selectedDocId === 'doc-bank-B')
    const documentLoadsBefore = await page.evaluate(() => window.mergeHarness.calls.filter(call => call.name === 'listDocuments').length)
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.finish('listBanks', ['bank-A', 'bank-B', 'bank-C'].map(id => ({...h.apiBank, id})))
    })
    await page.waitForFunction(() => window.mergeHarness.refreshDone)
    await settleRender(page)
    assert.equal(await page.evaluate(() => window.mergeApp.selectedKbId), 'bank-B')
    assert.deepEqual(await page.evaluate(() => window.mergeApp.docs.map(doc => doc.kbId)), ['bank-B'])
    assert.equal(await page.evaluate(() => window.mergeApp.selectedDocId), 'doc-bank-B')
    assert.deepEqual(await page.evaluate(before => window.mergeHarness.calls.filter(call => call.name === 'listDocuments')
      .slice(before).map(call => call.args[0]), documentLoadsBefore), ['bank-B'],
      '题库返回后只刷新当时的当前库 B，不能重新请求 A 的文档')
    assert.deepEqual(await page.evaluate(() => window.mergeApp.kbs.map(bank => bank.id)), ['bank-A', 'bank-B', 'bank-C'],
      '切库只能使旧文档请求失效，不能丢弃仍有效的全局题库列表与新增 C 库')
  })

  await providerCase('late selectKb document response cannot replace the newer bank', async page => {
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.held.listDocuments = true
      window.mergeApp.selectKb('bank-A')
    })
    await page.waitForFunction(() => window.mergeHarness.pending.listDocuments?.length === 1)
    await page.evaluate(() => window.mergeApp.selectKb('bank-B'))
    await page.waitForFunction(() => window.mergeHarness.pending.listDocuments.length === 2)
    await page.evaluate(() => { const h = window.mergeHarness; h.finish('listDocuments', [h.doc('bank-B')], 'bank-B') })
    await page.waitForFunction(() => window.mergeApp.docs[0]?.kbId === 'bank-B')
    await page.evaluate(() => { const h = window.mergeHarness; h.finish('listDocuments', [h.doc('bank-A')], 'bank-A') })
    await settleRender(page)
    assert.equal(await page.evaluate(() => window.mergeApp.docs[0]?.kbId), 'bank-B')
    assert.equal(await page.evaluate(() => window.mergeApp.selectedKbId), 'bank-B')
  })

  for (const phase of ['listBanks', 'listDocuments']) {
    await providerCase(`late refreshKbs ${phase} response cannot replace a bank selected afterwards`, async page => {
      await selectBank(page)
      await page.evaluate(phase => {
        const h = window.mergeHarness
        h.held[phase] = true
        h.refreshDone = false
        void window.mergeApp.refreshKbs().then(() => { h.refreshDone = true })
      }, phase)
      await page.waitForFunction(phase => window.mergeHarness.pending[phase]?.length === 1, phase)
      await page.evaluate(phase => { window.mergeHarness.held[phase] = false }, phase)
      await selectBank(page, 'bank-B')
      const before = await page.evaluate(() => window.mergeHarness.calls.filter(call => call.name === 'listDocuments').length)
      await page.evaluate(phase => {
        const h = window.mergeHarness
        h.finish(phase, phase === 'listBanks' ? [h.apiBank, {...h.apiBank, id:'bank-B'}] : [h.doc('bank-A')])
      }, phase)
      await page.waitForFunction(() => window.mergeHarness.refreshDone)
      await settleRender(page)
      assert.equal(await page.evaluate(() => window.mergeApp.docs[0]?.kbId), 'bank-B')
      assert.equal(await page.evaluate(() => window.mergeApp.selectedKbId), 'bank-B')
      assert.deepEqual(await page.evaluate(before => window.mergeHarness.calls.filter(call => call.name === 'listDocuments')
        .slice(before).map(call => call.args[0]), before), phase === 'listBanks' ? ['bank-B'] : [],
        '旧文档响应不能写回；题库返回后允许刷新当时当前库 B')
    })
  }

  for (const phase of ['getDocument', 'listDocuments']) {
    await providerCase(`late upload ${phase} response cannot overwrite a switched bank`, async page => {
      await selectBank(page)
      await page.evaluate(phase => {
        const h = window.mergeHarness
        h.held[phase] = true
        h.uploadDone = false
        void window.mergeApp.uploadDocument(new File(['synthetic'], 'same.txt', {type:'text/plain'}))
          .then(() => { h.uploadDone = true })
      }, phase)
      await page.waitForFunction(phase => window.mergeHarness.pending[phase]?.length === 1, phase)
      await page.evaluate(phase => { window.mergeHarness.held[phase] = false }, phase)
      await selectBank(page, 'bank-B')
      await page.evaluate(phase => {
        const h = window.mergeHarness
        h.finish(phase, phase === 'getDocument' ? {...h.doc('bank-A'), id:'doc-new'} : [{...h.doc('bank-A'), id:'doc-new'}])
      }, phase)
      await page.waitForFunction(() => window.mergeHarness.uploadDone)
      await settleRender(page)
      assert.equal(await page.evaluate(() => window.mergeApp.docs[0]?.kbId), 'bank-B')
      assert.equal(await page.evaluate(() => window.mergeApp.selectedDocId), '')
    })
  }

  await providerCase('late completed upload must not invalidate an in-flight document load for the new bank', async page => {
    await selectBank(page)
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.held.getDocument = true
      h.uploadDone = false
      void window.mergeApp.uploadDocument(new File(['synthetic'], 'same.txt', {type:'text/plain'}))
        .then(() => { h.uploadDone = true })
    })
    await page.waitForFunction(() => window.mergeHarness.pending.getDocument?.length === 1)
    await page.evaluate(() => {
      window.mergeHarness.held.listDocuments = true
      window.mergeApp.selectKb('bank-B')
    })
    await page.waitForFunction(() => window.mergeHarness.pending.listDocuments?.some(item => item.args[0] === 'bank-B'))
    const oldBankRefreshesBefore = await page.evaluate(() => window.mergeHarness.calls
      .filter(call => call.name === 'listDocuments' && call.args[0] === 'bank-A').length)
    await page.evaluate(() => { const h = window.mergeHarness; h.finish('getDocument', {...h.doc('bank-A'), id:'doc-new'}) })
    // B 的请求先发出、最后完成，A 的上传恰好在两者之间结束。
    await page.waitForFunction(() => window.mergeHarness.uploadDone
      || window.mergeHarness.pending.listDocuments.some(item => item.args[0] === 'bank-A'))
    const beforeBankBResponse = await page.evaluate(() => ({
      uploadDone: window.mergeHarness.uploadDone,
      pendingBanks: window.mergeHarness.pending.listDocuments.map(item => item.args[0]),
      oldBankRefreshes: window.mergeHarness.calls
        .filter(call => call.name === 'listDocuments' && call.args[0] === 'bank-A').length,
    }))
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.finish('listDocuments', [h.doc('bank-B')], 'bank-B')
      if (h.pending.listDocuments.some(item => item.args[0] === 'bank-A')) {
        h.finish('listDocuments', [{...h.doc('bank-A'), id:'doc-new'}], 'bank-A')
      }
    })
    await page.waitForFunction(() => window.mergeHarness.uploadDone)
    await settleRender(page)
    assert.equal(await page.evaluate(() => window.mergeApp.selectedKbId), 'bank-B')
    assert.deepEqual(await page.evaluate(() => window.mergeApp.docs.map(doc => doc.kbId)), ['bank-B'],
      '旧上传完成不能推进请求版本，导致新题库已发出的文档请求被丢弃')
    assert.equal(await page.evaluate(() => window.mergeApp.selectedDocId), '', '不能选中 A 库刚上传的文档')
    assert.deepEqual(beforeBankBResponse, {
      uploadDone:true, pendingBanks:['bank-B'], oldBankRefreshes:oldBankRefreshesBefore,
    }, 'B 响应尚未返回时，A 的上传应已结束，且不能再刷新 A 库文档')
  })

  for (const action of ['selectKb', 'refreshKbs', 'uploadDocument']) {
    await providerCase(`late ${action} response from an ended session cannot populate a new AppProvider`, async page => {
      await selectBank(page)
      await page.evaluate(action => {
        const h = window.mergeHarness
        h.held[action === 'uploadDocument' ? 'getDocument' : 'listDocuments'] = true
        if (action === 'selectKb') window.mergeApp.selectKb('old-bank')
        if (action === 'refreshKbs') void window.mergeApp.refreshKbs()
        if (action === 'uploadDocument') void window.mergeApp.uploadDocument(new File(['synthetic'], 'same.txt'))
      }, action)
      const pending = action === 'uploadDocument' ? 'getDocument' : 'listDocuments'
      await page.waitForFunction(name => window.mergeHarness.pending[name]?.length === 1, pending)
      await page.evaluate(() => {
        const h = window.mergeHarness
        h.invalidate()
        h.held.listDocuments = h.held.getDocument = false
        h.user = {...h.user, userId:'B', username:'fake-B', displayName:'新会话用户'}
        h.banks = [{...h.apiBank, id:'new-bank'}]
        window.remountMerge()
      })
      await page.waitForFunction(() => window.mergeApp.kbs[0]?.id === 'new-bank')
      await selectBank(page, 'new-bank')
      await page.evaluate(name => {
        const h = window.mergeHarness
        h.finish(name, name === 'getDocument' ? {...h.doc('bank-A'), id:'doc-new'} : [h.doc('old-bank')])
      }, pending)
      await page.waitForFunction(name => window.mergeHarness.pending[name].length === 0, pending)
      await settleRender(page)
      assert.equal(await page.evaluate(() => window.mergeApp.selectedKbId), 'new-bank')
      assert.deepEqual(await page.evaluate(() => window.mergeApp.docs.map(doc => doc.kbId)), ['new-bank'])
      assert.equal(await page.evaluate(() => window.mergeApp.selectedDocId), '')
    })
  }

  const notifications = await mount('context')
  await notifications.getByRole('button', {name:'通知', exact:true}).click()
  await notifications.getByRole('button', {name:'清除红点', exact:true}).click()
  await notifications.waitForFunction(() => window.mergeHarness.calls.some(call => call.name === 'markNotificationsRead'))
  assert.equal(await notifications.evaluate(() => window.mergeHarness.calls.some(call => call.name === 'clearUrgeBadge')), false,
    '教师清除题库通知时不能调用仅学生可用的催交接口')
  await notifications.evaluate(() => window.mergeApp.selectKb('bank-A'))
  await notifications.waitForFunction(() => window.mergeApp.docs[0]?.kbId === 'bank-A')
  await notifications.evaluate(() => {
    const h = window.mergeHarness
    h.notifications = [{id:'foreign', bank_id:'bank-B'}]; h.tick(10000)
  })
  await notifications.waitForFunction(() => window.mergeApp.bankNotifItems[0]?.id === 'foreign')
  assert.equal(await notifications.evaluate(() => window.mergeApp.docs[0]?.kbId), 'bank-A')
  assert.equal(await notifications.evaluate(() => window.mergeHarness.calls.some(call => call.name === 'listDocuments' && call.args[0] === 'bank-B')), false)
  await notifications.evaluate(() => {
    const h = window.mergeHarness; h.held.listDocuments = true
    h.notifications = [{id:'current', bank_id:'bank-A'}]; h.tick(10000)
  })
  await notifications.waitForFunction(() => window.mergeHarness.pending.listDocuments?.length === 1)
  await notifications.evaluate(() => {
    const h = window.mergeHarness; h.held.listDocuments = false
    window.mergeApp.selectKb('bank-B')
  })
  await notifications.waitForFunction(() => window.mergeApp.docs[0]?.kbId === 'bank-B')
  await notifications.evaluate(() => {
    const h = window.mergeHarness; h.finish('listDocuments', [h.doc('bank-A')])
  })
  await notifications.waitForFunction(() => window.mergeHarness.pending.listDocuments.length === 0)
  await settleRender(notifications)
  assert.equal(await notifications.evaluate(() => window.mergeApp.docs[0]?.kbId), 'bank-B')
  const before = await notifications.evaluate(() => window.mergeHarness.calls.length)
  await notifications.evaluate(() => { const h = window.mergeHarness; h.generation++; h.tick(10000) })
  assert.equal(await notifications.evaluate(() => window.mergeHarness.calls.length), before)
  await notifications.close()
  pass('notifications preserve selected bank, reject late document refresh and stop polling after identity change')

  const chat = await mount('context')
  await chat.evaluate(() => { window.mergeApp.selectKb('bank-A'); window.mergeApp.selectDoc('doc-bank-A') })
  await chat.waitForFunction(() => window.mergeApp.selectedDocId === 'doc-bank-A')
  await chat.evaluate(() => { window.mergeHarness.held.sendChatMessage = true; void window.mergeApp.sendChat('第一次') })
  await chat.waitForFunction(() => window.mergeHarness.pending.sendChatMessage?.length === 1)
  await chat.evaluate(() => { window.mergeApp.pauseChat(); void window.mergeApp.sendChat('第二次') })
  await chat.waitForFunction(() => window.mergeHarness.pending.sendChatMessage.length === 2)
  await chat.evaluate(() => window.mergeHarness.finish('sendChatMessage', {reply:'旧结果', questions:[]}))
  await chat.waitForFunction(() => window.mergeHarness.pending.sendChatMessage.length === 1)
  await settleRender(chat)
  assert.equal(await chat.evaluate(() => window.mergeApp.botThinking), true)
  assert.equal(await chat.evaluate(() => window.mergeApp.messages.some(message => message.text === '旧结果')), false)
  assert.equal(await chat.evaluate(() => [...window.mergeHarness.timers.values()].filter(timer => timer.delay === 1500).length), 1)
  await chat.evaluate(() => window.mergeHarness.finish('sendChatMessage', {reply:'新结果', questions:[]}))
  await chat.waitForFunction(() => !window.mergeApp.botThinking && window.mergeApp.messages.some(message => message.text === '新结果'))
  await chat.evaluate(() => { void window.mergeApp.generate().then(() => { window.mergeHarness.generationFinished = true }) })
  await chat.waitForFunction(() => window.mergeHarness.calls.some(call => call.name === 'getGenerationProgress'))
  const progressCalls = await chat.evaluate(() => window.mergeHarness.calls.filter(call => call.name === 'getGenerationProgress').length)
  await chat.evaluate(() => { window.mergeHarness.generation++ })
  await chat.waitForFunction(() => window.mergeHarness.generationFinished)
  assert.equal(await chat.evaluate(() => window.mergeHarness.calls.filter(call => call.name === 'getGenerationProgress').length), progressCalls)
  await chat.evaluate(() => window.unmountMerge())
  assert.equal(await chat.evaluate(() => window.mergeHarness.timers.size), 0)
  await chat.close()
  assert.deepEqual(errors, [])
  pass('paused chat keeps newer results/ownership, generation polling stops on identity change, unmount removes all polling')
  console.log(`主线整合回归：${passed} 组通过，${failures.length} 组失败`)
  assert.deepEqual(failures, [], '整合回归发现产品行为与约定不符；保留失败断言，不修改产品代码')
} finally {
  await browser.close()
}
