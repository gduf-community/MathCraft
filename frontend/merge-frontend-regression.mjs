/* global URL, console, process, window */
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
  backend: exports.map(([, asyncKeyword, name]) => `export const ${name} = ${asyncKeyword ?? ''}(...args) => window.mergeHarness.backend.${name}(...args);`).join('\n'),
  session: `
    export const getSessionGeneration = () => window.mergeHarness.generation;
    export const assertCurrentSession = started => {
      if (started !== getSessionGeneration()) throw new Error('synthetic session ended');
    };
  `,
  AuthContext: `export const useAuth = () => ({user: window.mergeHarness.user, logout: async () => {}});`,
}
const bundle = await build({
  stdin: { contents: `
    import React, {useEffect} from 'react';
    import {createRoot} from 'react-dom/client';
    import {AppProvider, useApp} from './src/store/AppContext';
    import BankCreateModal from './src/components/tabs/BankTab/BankCreateModal';
    import BankEditModal from './src/components/tabs/BankTab/BankEditModal';
    import BankViewModal from './src/components/tabs/BankTab/BankViewModal';
    import TopBar from './src/components/layout/TopBar';
    import ChatInput from './src/components/tabs/GenerateTab/ChatInput';
    function Harness() {
      const app = useApp(), h = window.mergeHarness;
      useEffect(() => { window.mergeApp = app; }, [app]);
      const callbacks = {onClose: () => h.closed++, onChanged: () => h.changed++};
      return <>
        <TopBar/>
        {h.mode === 'create' && <BankCreateModal {...callbacks}/>}
        {h.mode === 'edit' && <BankEditModal bank={h.bank} {...callbacks}/>}
        {h.mode === 'view' && <BankViewModal bank={h.bank} {...callbacks}/>}
        <ChatInput/>
        <output data-testid="docs">{JSON.stringify(app.docs)}</output>
        <output data-testid="messages">{JSON.stringify(app.messages)}</output>
      </>;
    }
    const root = createRoot(document.getElementById('root'));
    window.unmountMerge = () => root.unmount();
    root.render(<AppProvider><Harness/></AppProvider>);
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
async function mount(mode, role = 'teacher', memberRole = 'creator') {
  const page = await browser.newPage()
  await page.route('**/*', route => route.abort())
  page.on('pageerror', error => errors.push(error.message))
  await page.setContent('<div id="root"></div>')
  await page.evaluate(({ mode, role, memberRole }) => {
    const h = window.mergeHarness = { mode, generation: 0, closed: 0, changed: 0,
      calls: [], timers: new Map(), timerId: 0,
      user: {userId:'A', username:'fake-A', displayName:'合成用户', role, emailVerified:false},
      notifications: [], held: {}, pending: {}, preview: '# 远端文档预览',
    }
    window.setInterval = (action, delay) => { const id = ++h.timerId; h.timers.set(id, {action, delay}); return id }
    window.clearInterval = id => h.timers.delete(id)
    h.tick = delay => { for (const timer of [...h.timers.values()]) if (timer.delay === delay) timer.action() }
    h.doc = id => ({id:'doc-' + id, bank_id:id, name:id + '.txt', format:'TXT', size_bytes:12,
      status:'ready', progress:100, is_scanned:false, chunk_count:1, created_at:'2026-11-10'})
    h.apiBank = {id:'bank-A', name:'合成题库', code:'fake-code', creator:{id:'A', display_name:'合成用户'},
      member_count:1, capacity:100, source:'owned', quitted:false, my_role:memberRole,
      can_upload_document:memberRole !== 'readonly', can_download_document:true,
      can_delete_document:memberRole !== 'readonly', can_manage_members:memberRole === 'creator',
      can_edit_bank:memberRole === 'creator', can_transfer_bank:false, can_delete_bank:memberRole === 'creator'}
    h.bank = {id:'bank-A', name:'合成题库', code:'fake-code', creator:'合成用户',
      memberCount:1, capacity:100, source:'owned', myRole:memberRole,
      canUpload:memberRole !== 'readonly', canDownload:true, canDeleteDoc:memberRole !== 'readonly',
      canManageMembers:memberRole === 'creator', canEdit:memberRole === 'creator', canDelete:memberRole === 'creator',
      docs:[{id:'doc-bank-A', name:'bank-A.txt', format:'TXT', size:'12 B', status:'parsing', stage:'正在解析', progress:25}],
      members:[{id:'member-A', userId:'A', name:'合成用户', role:memberRole, isMe:true, isCreator:memberRole === 'creator'}]}
    const defaults = {
      listBanks: () => [h.apiBank], latestBatch: () => ({batch_id:null, questions:[]}),
      listFavoriteGroups: () => [], listFavorites: () => [], listPapers: () => [], listSpaces: () => [],
      listNotifications: () => ({items:h.notifications, unread_count:h.notifications.length}),
      listDocuments: id => [h.doc(id)], listBankMembers: () => [],
      mapBankToKnowledgeBase: bank => ({id:bank.id, name:bank.name}),
      mapDocument: doc => ({id:doc.id, kbId:doc.bank_id, name:doc.name,
        status:doc.status, stage:doc.stage, progress:doc.progress, api:doc}),
      mapQuestion: question => question, formatFileSize: bytes => bytes + ' B',
      fetchDocumentText: () => { if (h.previewError) throw new Error(h.previewError); return h.preview },
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
    h.backend = new Proxy({}, {get: (target, name) => name in target ? target[name] : (...args) => {
      h.calls.push({name, args})
      if (h.held[name]) return new Promise((resolve, reject) => {
        ;(h.pending[name] ??= []).push({resolve, reject})
      })
      if (!(name in defaults)) throw new Error('unexpected API: ' + String(name))
      return defaults[name](...args)
    }})
    h.finish = (name, value) => h.pending[name].shift().resolve(value)
  }, {mode, role, memberRole})
  await page.addScriptTag({ content: bundle.outputFiles[0].text })
  await page.waitForFunction(() => window.mergeApp && window.mergeHarness.calls.some(call => call.name === 'listSpaces'))
  return page
}
async function attachFiles(page) {
  await page.locator('input[type=file]').setInputFiles({name:'one.txt', mimeType:'text/plain', buffer:Buffer.from('synthetic document')})
  // 原组件一次选择一个文件，使用两次选择验证后台队列。
  await page.locator('input[type=file]').setInputFiles({name:'two.txt', mimeType:'text/plain', buffer:Buffer.from('synthetic document')})
}
try {
  const student = await mount('create', 'student')
  assert.equal(await student.getByRole('heading', {name:'新建题库', exact:true}).count(), 0)
  await student.close()

  for (const fail of [false, true]) {
    const create = await mount('create')
    await attachFiles(create)
    if (fail) await create.evaluate(() => {
      window.mergeHarness.backend.createBankWithDocument = () => { throw new Error('synthetic creation failure') }
    })
    await create.getByRole('button', {name:'创建', exact:true}).click()
    if (fail) await create.waitForFunction(() => window.mergeHarness.closed === 1)
    else await create.waitForFunction(() => window.mergeHarness.calls.some(call => call.name === 'uploadDocument'))
    const uploads = await create.evaluate(() => window.mergeHarness.calls.filter(call => call.name === 'uploadDocument'))
    assert.equal(uploads.length, fail ? 0 : 1)
    if (!fail) assert.equal(uploads[0].args[0], 'bank-A')
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
  console.log('PASS: teacher-only creation, background upload queue, first failure and changed session stop follow-up writes')

  for (const memberRole of ['creator', 'editor', 'readonly']) {
    const view = await mount(memberRole === 'creator' ? 'edit' : 'view', 'teacher', memberRole)
    assert.equal(await view.getByLabel('成员登录账号').count(), memberRole === 'creator' ? 1 : 0)
    assert.equal(await view.getByTitle('删除文档').count(), memberRole === 'readonly' ? 0 : 1)
    assert.equal(await view.locator('input[type=file]').count(), memberRole === 'readonly' ? 0 : 1)
    await view.getByText('正在解析 25%', {exact:true}).waitFor()
    await view.getByTitle('查看文档').click()
    await view.getByRole('heading', {name:'远端文档预览', exact:true}).waitFor()
    await view.getByLabel('关闭文档预览').click()
    assert.equal(await view.evaluate(() => window.mergeHarness.closed), 0, '关闭预览不得关闭父弹窗')
    await view.evaluate(() => { window.mergeHarness.preview = '' })
    await view.getByTitle('查看文档').click()
    await view.getByText('文档暂无可预览内容', {exact:true}).waitFor()
    await view.getByRole('dialog').dispatchEvent('click')
    assert.equal(await view.evaluate(() => window.mergeHarness.closed), 0)
    await view.evaluate(() => { window.mergeHarness.previewError = 'synthetic preview failure' })
    await view.getByTitle('查看文档').click()
    await view.getByRole('alert').filter({hasText:'synthetic preview failure'}).waitFor()
    await view.close()
  }
  console.log('PASS: creator/editor/readonly UI capabilities, ingestion status, preview success/empty/error and independent close')

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
  assert.equal(await notifications.evaluate(() => window.mergeApp.docs[0]?.kbId), 'bank-B')
  const before = await notifications.evaluate(() => window.mergeHarness.calls.length)
  await notifications.evaluate(() => { const h = window.mergeHarness; h.generation++; h.tick(10000) })
  assert.equal(await notifications.evaluate(() => window.mergeHarness.calls.length), before)
  await notifications.close()
  console.log('PASS: notifications preserve selected bank, reject late document refresh and stop polling after identity change')

  const chat = await mount('context')
  await chat.evaluate(() => { window.mergeApp.selectKb('bank-A'); window.mergeApp.selectDoc('doc-bank-A') })
  await chat.waitForFunction(() => window.mergeApp.selectedDocId === 'doc-bank-A')
  await chat.evaluate(() => { window.mergeHarness.held.sendChatMessage = true; void window.mergeApp.sendChat('第一次') })
  await chat.waitForFunction(() => window.mergeHarness.pending.sendChatMessage?.length === 1)
  await chat.evaluate(() => { window.mergeApp.pauseChat(); void window.mergeApp.sendChat('第二次') })
  await chat.waitForFunction(() => window.mergeHarness.pending.sendChatMessage.length === 2)
  await chat.evaluate(() => window.mergeHarness.finish('sendChatMessage', {reply:'旧结果', questions:[]}))
  await chat.waitForFunction(() => window.mergeHarness.pending.sendChatMessage.length === 1)
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
  console.log('PASS: paused chat keeps newer results/ownership, generation polling stops on identity change, unmount removes all polling')
} finally {
  await browser.close()
}
