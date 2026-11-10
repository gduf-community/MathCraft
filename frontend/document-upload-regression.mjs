/* global process, URL, console, window, document, File, DataTransfer, Event, DragEvent */
/** 离线真实组件回归：真实弹窗、上传 hook、banks 映射和 Toast；仅替换请求、会话与预览边界。 */
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
const source = await readFile(new URL('./src/api/backend.ts', import.meta.url), 'utf8')
const requestExports = [...source.matchAll(/export (?:async )?function (\w+)/g)]
const stubs = {
  backend: requestExports.map(([, name]) => name === 'formatFileSize'
    ? 'export const formatFileSize = size => size + " B";'
    : `export const ${name} = (...args) => window.uploadHarness.invoke('${name}', args);`).join('\n'),
  session: `
    export const getSessionGeneration = () => window.uploadHarness.generation;
    export const assertCurrentSession = generation => {
      if (generation !== getSessionGeneration()) throw new Error('合成会话已结束');
    };
    export const onSessionCleared = () => () => {};
  `,
  AuthContext: `export const useAuth = () => ({user:{userId:'synthetic-user', role:'teacher'}});`,
  AppContext: `
    import {useToast} from '${fileURLToPath(new URL('./src/store/ToastContext.tsx', import.meta.url)).replaceAll('\\', '/')}';
    export const useApp = () => ({role:window.uploadHarness.role, ...useToast()});
  `,
  documentPreview: `export const openPdfDocument = (...args) => window.uploadHarness.invoke('openPdfDocument', args);`,
  // 预览实现由独立任务负责；这里只验证列表路由与 docFormat 契约。
  DocPreviewModal: `
    export default function Preview(props) {
      window.uploadHarness.preview = {id:props.docId, format:props.docFormat};
      return <button onClick={props.onClose}>关闭合成预览</button>;
    }
  `,
}
const bundle = await build({
  stdin: {contents: `
    import React, {useEffect} from 'react';
    import {createRoot} from 'react-dom/client';
    import {ToastProvider, useToast} from './src/store/ToastContext';
    import Toast from './src/components/ui/Toast';
    import * as banks from './src/api/banks';
    import BankCreateModal from './src/components/tabs/BankTab/BankCreateModal';
    import BankEditModal from './src/components/tabs/BankTab/BankEditModal';
    import BankViewModal from './src/components/tabs/BankTab/BankViewModal';
    window.uploadApi = banks;
    function Harness() {
      const {toast} = useToast(), h = window.uploadHarness;
      useEffect(() => { if (toast) h.toasts.push(toast); }, [toast, h]);
      const callbacks = {onClose:() => h.closed++, onChanged:() => h.changed++};
      return <>
        {h.mode === 'create' && <BankCreateModal {...callbacks}/>}
        {h.mode === 'edit' && <BankEditModal bank={h.bank} {...callbacks}/>}
        {h.mode === 'view' && <BankViewModal bank={h.bank} {...callbacks}/>}
        <Toast/>
      </>;
    }
    const root = createRoot(document.getElementById('root'));
    root.render(<ToastProvider><Harness/></ToastProvider>);
  `, resolveDir:fileURLToPath(new URL('.', import.meta.url)), loader:'jsx'},
  bundle:true, write:false, format:'iife', jsx:'automatic',
  plugins:[{name:'offline-upload-boundaries', setup(builder) {
    builder.onResolve({filter:/\/(backend|session|AuthContext|AppContext|documentPreview|DocPreviewModal)$/}, args => ({
      path:args.path.split('/').at(-1), namespace:'upload-fakes',
    }))
    builder.onLoad({filter:/.*/, namespace:'upload-fakes'}, args => ({
      contents:stubs[args.path], loader:'jsx', resolveDir:fileURLToPath(new URL('.', import.meta.url)),
    }))
  }}],
})
const browser = await chromium.launch({executablePath:process.env.AUTH_BROWSER ?? join(
  homedir(), 'AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe',
), headless:true})
const runtimeErrors = []
const passed = []

async function mount(mode = 'create', memberRole = 'creator', documents = []) {
  const page = await browser.newPage({viewport:{width:1000, height:1100}})
  await page.route('**/*', route => route.abort())
  page.on('pageerror', error => runtimeErrors.push(error.message))
  await page.setContent('<div id="root"></div>')
  await page.evaluate(({mode, memberRole, documents}) => {
    const editable = memberRole !== 'readonly'
    const h = window.uploadHarness = {
      mode, role:'teacher', generation:0, closed:0, changed:0, calls:[], toasts:[],
      held:{}, pending:{}, failures:{}, preview:null, apiDocs:documents,
    }
    h.apiBank = {id:'synthetic-bank', name:'合成题库', code:'synthetic-code',
      creator:{id:'synthetic-user', display_name:'合成教师'}, member_count:1, capacity:100,
      source:'owned', my_role:memberRole, can_upload_document:editable, can_download_document:true,
      can_delete_document:editable, can_manage_members:memberRole === 'creator',
      can_edit_bank:memberRole === 'creator', can_transfer_bank:false, can_delete_bank:false}
    h.bank = {id:h.apiBank.id, name:h.apiBank.name, code:h.apiBank.code, creator:'合成教师',
      memberCount:1, capacity:100, source:'owned', myRole:memberRole,
      canUpload:editable, canDownload:true, canDeleteDoc:editable,
      canManageMembers:memberRole === 'creator', canEdit:memberRole === 'creator',
      docs:documents.map(doc => ({id:doc.id, name:doc.name, format:doc.format, size:'10 B',
        status:doc.status, stage:doc.stage, progress:doc.progress,
        errorMessage:doc.error_message, ocrStatus:doc.ocr_status})), members:[]}
    h.defaults = {
      createBank:name => ({...h.apiBank, name}),
      createBankWithDocument:(name, file) => ({bank:{...h.apiBank, name},
        document:{document_id:'synthetic-first', name:file.name, eta_minutes:1, status:'uploaded'}}),
      uploadDocument:(_bank, file) => ({document_id:'synthetic-' + file.name, eta_minutes:1}),
      getBank:() => h.apiBank,
      listDocuments:() => h.apiDocs,
      listBankMembers:() => [],
      updateBank:(_id, patch) => Object.assign(h.apiBank, patch),
      deleteDocument:(_id, docId) => { h.apiDocs = h.apiDocs.filter(doc => doc.id !== docId) },
      downloadDocument:() => {},
      openPdfDocument:() => {},
      reprocessDocument:(_id, docId) => {
        h.apiDocs = h.apiDocs.map(doc => doc.id === docId
          ? {...doc, status:'parsing', stage:'重新排队', progress:0, error_message:null} : doc)
      },
    }
    h.invoke = async (name, args) => {
      h.calls.push({name, args})
      const key = name + ':' + (args[1]?.name ?? '')
      if (h.failures[key] || h.failures[name]) {
        const failureKey = h.failures[key] ? key : name
        const message = h.failures[failureKey]
        delete h.failures[failureKey]
        throw new Error(message)
      }
      if (h.held[name]) return new Promise((resolve, reject) => {
        ;(h.pending[name] ??= []).push({resolve, reject, args})
      })
      if (!(name in h.defaults)) throw new Error('未预期的离线 API：' + name)
      return h.defaults[name](...args)
    }
    h.finish = name => {
      const pending = h.pending[name].shift()
      pending.resolve(h.defaults[name](...pending.args))
    }
    h.reject = (name, message) => h.pending[name].shift().reject(new Error(message))
  }, {mode, memberRole, documents})
  await page.addScriptTag({content:bundle.outputFiles[0].text})
  await page.getByRole('dialog').first().waitFor()
  return page
}

async function choose(page, descriptors, drop = false) {
  await page.evaluate(({descriptors, drop}) => {
    const transfer = new DataTransfer()
    for (const descriptor of descriptors) {
      const {name, text = 'synthetic document', lastModified = 1} = descriptor
      transfer.items.add(new File([text], name, {lastModified, type:'application/octet-stream'}))
    }
    if (drop) {
      const zone = document.querySelector('button[aria-label="选择或拖入文档"]')
      zone.dispatchEvent(new DragEvent('dragover', {bubbles:true, cancelable:true, dataTransfer:transfer}))
      zone.dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:transfer}))
    } else {
      const input = document.querySelector('input[type=file]')
      input.files = transfer.files
      input.dispatchEvent(new Event('change', {bubbles:true}))
    }
  }, {descriptors, drop})
}

async function toast(page, variant, contains) {
  await page.waitForFunction(({variant, contains}) => {
    const latest = window.uploadHarness.toasts.at(-1)
    return latest?.variant === variant && latest.text.includes(contains)
  }, {variant, contains})
  const color = {error:'border-red-700', success:'border-emerald-700', info:'border-slate-700'}[variant]
  assert.ok(await page.locator(`.${color}`).count(), '真实 Toast 使用正确语义颜色')
}

function fixture(id, format = 'TXT', status = 'ready') {
  return {id, name:`${id}.${format.toLowerCase()}`, format, status, stage:'合成处理阶段',
    progress:status === 'ready' ? 100 : 15, size_bytes:10,
    error_message:status === 'failed' ? '合成 OCR 失败：请重试\n第二行详情' : null,
    ocr_status:status === 'failed' ? 'failed' : null}
}

try {
  const validation = await mount()
  const input = validation.locator('input[type=file]')
  assert.equal(await input.getAttribute('multiple'), '')
  assert.equal(await input.getAttribute('accept'), '.pdf,.docx,.xlsx,.md,.markdown,.txt')
  await choose(validation, [
    ...['PDF', 'DOCX', 'XLSX', 'md', 'markdown', 'TXT'].map(format => ({name:`valid.${format}`})),
    {name:'empty.txt', text:''}, {name:'bad.exe'}, {name:'bad.constructor'}, {name:'no-extension'},
  ])
  assert.equal(await validation.getByRole('listitem').count(), 6)
  await toast(validation, 'error', '空文件')
  assert.match(await validation.evaluate(() => window.uploadHarness.toasts.at(-1).text), /格式不支持/)
  await choose(validation, [
    {name:'same.txt', text:'one', lastModified:10},
    {name:'same.txt', text:'one', lastModified:10},
    {name:'same.txt', text:'different size', lastModified:10},
    {name:'same.txt', text:'one', lastModified:11},
  ], true)
  assert.equal(await validation.getByRole('listitem').count(), 9)
  await choose(validation, [{name:'same.txt', text:'one', lastModified:10}])
  assert.equal(await validation.getByRole('listitem').count(), 9)
  await toast(validation, 'error', '重复')
  const zone = validation.getByRole('button', {name:'选择或拖入文档'})
  for (const key of ['Enter', 'Space']) {
    await zone.focus()
    const chooser = validation.waitForEvent('filechooser')
    await zone.press(key)
    assert.equal((await chooser).isMultiple(), true)
  }
  assert.match(await zone.getAttribute('class'), /focus-visible:outline/)
  await zone.dispatchEvent('dragover')
  await validation.waitForFunction(() => document.querySelector('button[aria-label="选择或拖入文档"]').className.includes('border-primary bg-primary-light'))
  assert.match(await zone.getAttribute('class'), /border-primary bg-primary-light/)
  await zone.dispatchEvent('dragleave')
  await validation.waitForFunction(() => !document.querySelector('button[aria-label="选择或拖入文档"]').className.includes('border-primary bg-primary-light'))
  assert.doesNotMatch(await zone.getAttribute('class'), /border-primary bg-primary-light/)
  passed.push('共用格式/空文件/同批及跨批去重、同名不同大小或时间、markdown 徽标、键盘与拖放高亮')
  await validation.close()

  const draft = await mount()
  await draft.getByLabel('题库名称', {exact:true}).fill('保留的合成草稿')
  await draft.locator('input[type=file]').setInputFiles([
    {name:'first.pdf', mimeType:'application/pdf', buffer:Buffer.from('synthetic pdf')},
    {name:'second.txt', mimeType:'text/plain', buffer:Buffer.from('synthetic txt')},
  ])
  await draft.evaluate(() => { window.uploadHarness.held.createBankWithDocument = true })
  await draft.getByRole('button', {name:'创建', exact:true}).click()
  await draft.waitForFunction(() => window.uploadHarness.pending.createBankWithDocument?.length === 1)
  assert.equal(await draft.getByRole('listitem').count(), 2)
  assert.equal(await draft.getByLabel('题库名称', {exact:true}).inputValue(), '保留的合成草稿')
  assert.equal(await draft.getByRole('button', {name:'关闭新建题库'}).isDisabled(), true)
  assert.equal(await draft.getByRole('button', {name:'取消', exact:true}).isDisabled(), true)
  await draft.getByLabel('题库名称', {exact:true}).press('Escape')
  assert.equal(await draft.evaluate(() => window.uploadHarness.closed), 0)
  await choose(draft, [{name:'busy.txt'}], true)
  await toast(draft, 'error', '等待本批完成')
  await draft.evaluate(() => window.uploadHarness.reject('createBankWithDocument', '服务端拒绝：超过文件大小限制'))
  await toast(draft, 'error', '超过文件大小限制')
  assert.equal(await draft.getByRole('listitem').count(), 2)
  assert.equal(await draft.getByLabel('题库名称', {exact:true}).isEnabled(), true)
  assert.equal(await draft.getByLabel('题库名称', {exact:true}).inputValue(), '保留的合成草稿')
  assert.equal(await draft.evaluate(() => window.uploadHarness.calls.filter(call => call.name === 'uploadDocument').length), 0)
  await draft.getByRole('button', {name:'创建', exact:true}).click()
  await draft.waitForFunction(() => window.uploadHarness.pending.createBankWithDocument?.length === 1)
  await draft.evaluate(() => window.uploadHarness.finish('createBankWithDocument'))
  await draft.waitForFunction(() => window.uploadHarness.closed === 1)
  assert.equal(await draft.getByRole('listitem').count(), 0)
  await toast(draft, 'success', '全部受理')
  assert.equal(await draft.evaluate(() => window.uploadHarness.changed), 2)
  passed.push('真实 multiple 选择、首请求未受理/大小拒绝保留名称与所有文件、忙时禁止关闭与加入、失败可重试')
  await draft.close()

  const partial = await mount()
  await choose(partial, [{name:'one.pdf'}, {name:'two.docx'}, {name:'three.xlsx'}], true)
  await partial.evaluate(() => {
    const h = window.uploadHarness
    h.held.createBankWithDocument = true
    h.held.uploadDocument = true
  })
  await partial.getByRole('button', {name:'创建', exact:true}).click()
  await partial.waitForFunction(() => window.uploadHarness.pending.createBankWithDocument?.length === 1)
  assert.equal(await partial.evaluate(() => window.uploadHarness.calls.filter(call => call.name === 'uploadDocument').length), 0)
  await partial.evaluate(() => window.uploadHarness.finish('createBankWithDocument'))
  await partial.waitForFunction(() => window.uploadHarness.pending.uploadDocument?.length === 1)
  assert.equal(await partial.getByRole('listitem').count(), 2)
  assert.equal(await partial.getByLabel('题库名称', {exact:true}).isDisabled(), true)
  await partial.evaluate(() => window.uploadHarness.reject('uploadDocument', '合成的第二个文件失败'))
  await partial.waitForFunction(() => window.uploadHarness.calls.filter(call => call.name === 'uploadDocument').length === 2)
  assert.equal(await partial.evaluate(() => window.uploadHarness.pending.uploadDocument.length), 1)
  await partial.evaluate(() => window.uploadHarness.finish('uploadDocument'))
  await partial.getByRole('button', {name:'重试未提交文件'}).waitFor()
  assert.equal(await partial.getByRole('listitem').count(), 1)
  assert.match(await partial.getByRole('listitem').innerText(), /two.docx/)
  assert.equal(await partial.evaluate(() => window.uploadHarness.closed), 0)
  await partial.getByRole('button', {name:'重试未提交文件'}).click()
  await partial.waitForFunction(() => window.uploadHarness.pending.uploadDocument?.length === 1)
  await partial.evaluate(() => window.uploadHarness.finish('uploadDocument'))
  await partial.waitForFunction(() => window.uploadHarness.closed === 1)
  assert.equal(await partial.evaluate(() => window.uploadHarness.calls.filter(call => call.name === 'createBankWithDocument').length), 1)
  assert.deepEqual(await partial.evaluate(() => window.uploadHarness.calls.filter(call => call.name === 'uploadDocument').map(call => [call.args[0], call.args[1].name])), [
    ['synthetic-bank', 'two.docx'], ['synthetic-bank', 'three.xlsx'], ['synthetic-bank', 'two.docx'],
  ])
  await toast(partial, 'success', '全部受理')
  passed.push('拖放全部文件串行提交、部分成功保留 bankId、仅重试失败文件、成功文件不重复上传或建库')
  await partial.close()

  const empty = await mount()
  await empty.getByRole('button', {name:'创建', exact:true}).click()
  await toast(empty, 'error', '题库名称')
  await empty.getByLabel('题库名称', {exact:true}).fill('合成空题库')
  await empty.evaluate(() => { window.uploadHarness.failures.createBank = '合成空库创建失败' })
  await empty.getByRole('button', {name:'创建', exact:true}).click()
  await toast(empty, 'error', '合成空库创建失败')
  assert.equal(await empty.getByLabel('题库名称', {exact:true}).inputValue(), '合成空题库')
  await empty.getByRole('button', {name:'创建', exact:true}).click()
  await empty.waitForFunction(() => window.uploadHarness.closed === 1)
  await toast(empty, 'success', '创建成功')
  passed.push('名称校验、空库创建失败保留草稿、空库创建成功反馈')
  await empty.close()

  for (const mode of ['edit', 'view']) {
    const page = await mount(mode)
    await page.evaluate(() => { window.uploadHarness.held.uploadDocument = true })
    await choose(page, [{name:'batch-a.txt'}, {name:'batch-b.markdown'}], mode === 'view')
    await page.waitForFunction(() => window.uploadHarness.pending.uploadDocument?.length === 1)
    await choose(page, [{name:'busy-added.pdf'}], true)
    await toast(page, 'error', '等待本批完成')
    assert.equal(await page.evaluate(() => window.uploadHarness.calls.filter(call => call.name === 'uploadDocument').length), 1)
    const closeName = mode === 'edit' ? '关闭题库信息' : '关闭查看题库'
    assert.equal(await page.getByRole('button', {name:closeName}).isDisabled(), true)
    await page.getByRole('button', {name:'选择或拖入文档'}).press('Escape')
    assert.equal(await page.evaluate(() => window.uploadHarness.closed), 0)
    await page.evaluate(() => window.uploadHarness.finish('uploadDocument'))
    await page.waitForFunction(() => window.uploadHarness.calls.filter(call => call.name === 'uploadDocument').length === 2)
    assert.equal(await page.evaluate(() => window.uploadHarness.changed), 1)
    assert.equal(await page.evaluate(() => window.uploadHarness.pending.uploadDocument.length), 1)
    await page.evaluate(() => window.uploadHarness.reject('uploadDocument', '合成上传失败'))
    await toast(page, 'error', '合成上传失败')
    await page.evaluate(() => { window.uploadHarness.held.uploadDocument = false })
    await choose(page, [{name:'batch-a.txt'}, {name:'batch-b.markdown'}, {name:'invalid.exe'}, {name:'zero.pdf', text:''}])
    await toast(page, 'error', '空文件')
    assert.deepEqual(await page.evaluate(() => window.uploadHarness.calls.filter(call => call.name === 'uploadDocument').map(call => call.args[1].name)), ['batch-a.txt', 'batch-b.markdown', 'batch-b.markdown'])
    assert.equal(await page.evaluate(() => window.uploadHarness.changed), 2)
    await choose(page, [{name:'next.pdf'}, {name:'next.docx'}], true)
    await toast(page, 'success', '全部受理')
    assert.equal(await page.evaluate(() => window.uploadHarness.changed), 4)
    await page.getByRole('button', {name:closeName}).click()
    assert.equal(await page.evaluate(() => window.uploadHarness.closed), 1)
    passed.push(`${mode}：真实批量上传、busy 红色拒绝/禁止关闭、失败继续且可重选、已受理去重、每次 onChanged`)
    await page.close()
  }

  for (const mode of ['edit', 'view']) {
    const documents = [fixture('failed', 'PDF', 'failed'), fixture('plain', 'TXT'), fixture('markdown', 'MD'), fixture('word', 'DOCX'), fixture('sheet', 'XLSX')]
    const page = await mount(mode, 'creator', documents)
    const mapped = await page.evaluate(async () => (await window.uploadApi.getBankDetail('synthetic-bank')).docs[0])
    assert.equal(mapped.errorMessage, documents[0].error_message)
    assert.equal(mapped.ocrStatus, 'failed')
    const expand = page.getByRole('button', {name:'展开失败详情'})
    assert.equal(await expand.getAttribute('aria-expanded'), 'false')
    await expand.focus()
    await expand.press('Enter')
    const detail = page.getByRole('textbox', {name:'failed.pdf的失败详情'})
    assert.equal(await page.getByRole('button', {name:'收起失败详情'}).getAttribute('aria-expanded'), 'true')
    assert.match(await detail.inputValue(), /合成 OCR 失败[\s\S]*OCR 状态：failed/)
    await detail.focus()
    await detail.press('ControlOrMeta+A')
    assert.ok(await detail.evaluate(element => element.selectionEnd > element.selectionStart))
    const row = id => page.getByRole('listitem').filter({hasText:`${id}.`})
    await row('failed').getByRole('button', {name:'查看文档'}).click()
    await page.waitForFunction(() => window.uploadHarness.calls.some(call => call.name === 'openPdfDocument'))
    assert.deepEqual(await page.evaluate(() => window.uploadHarness.calls.find(call => call.name === 'openPdfDocument').args), ['synthetic-bank', 'failed'])
    await page.evaluate(() => { window.uploadHarness.failures.openPdfDocument = '合成 PDF 打开失败' })
    await row('failed').getByRole('button', {name:'查看文档'}).click()
    await toast(page, 'error', '合成 PDF 打开失败')
    for (const [id, format] of [['plain', 'TXT'], ['markdown', 'MD']]) {
      await row(id).getByRole('button', {name:'查看文档'}).click()
      assert.deepEqual(await page.evaluate(() => window.uploadHarness.preview), {id, format})
      await page.getByRole('button', {name:'关闭合成预览'}).click()
    }
    for (const id of ['word', 'sheet']) {
      await row(id).getByRole('button', {name:'查看文档'}).click()
      await toast(page, 'info', '暂不支持内联预览')
      assert.equal(await page.getByRole('button', {name:'关闭合成预览'}).count(), 0)
      await row(id).getByRole('button', {name:'下载文档'}).click()
    }
    assert.equal(await page.evaluate(() => window.uploadHarness.calls.filter(call => call.name === 'downloadDocument').length), 2)
    await page.evaluate(() => { window.uploadHarness.failures.reprocessDocument = '合成重试失败' })
    await page.getByRole('button', {name:'重新解析', exact:true}).click()
    await toast(page, 'error', '合成重试失败')
    await page.getByRole('button', {name:'重新解析', exact:true}).click()
    await toast(page, 'success', '重新排队')
    await page.getByText('重新排队 0%', {exact:true}).waitFor()
    assert.equal(await page.evaluate(() => window.uploadHarness.changed), 1)
    await row('plain').getByRole('button', {name:'删除文档'}).click()
    await page.waitForFunction(() => window.uploadHarness.changed === 2)
    assert.equal(await row('plain').count(), 0)
    passed.push(`${mode}：真实 mapDoc 映射、可访问错误展开/文本选择、重试/删除回调、PDF 代理及失败红色、MD/TXT 格式、Office 下载`)
    await page.close()
  }

  const readonly = await mount('view', 'readonly', [fixture('readonly-failed', 'TXT', 'failed')])
  assert.equal(await readonly.locator('input[type=file]').count(), 0)
  assert.equal(await readonly.getByRole('button', {name:'重新解析', exact:true}).count(), 0)
  assert.equal(await readonly.getByRole('button', {name:'删除文档'}).count(), 0)
  await readonly.getByRole('button', {name:'展开失败详情'}).click()
  assert.match(await readonly.getByRole('textbox').inputValue(), /合成 OCR 失败/)
  await readonly.close()
  const editor = await mount('view', 'editor', [fixture('editor-failed', 'TXT', 'failed')])
  assert.equal(await editor.getByRole('button', {name:'重新解析', exact:true}).count(), 1)
  await editor.close()
  passed.push('只读可展开失败详情但无上传/删除/重试；可编辑成员有重试入口')

  const stale = await mount()
  await choose(stale, [{name:'session-a.pdf'}, {name:'session-b.txt'}])
  await stale.evaluate(() => { window.uploadHarness.held.createBankWithDocument = true })
  await stale.getByRole('button', {name:'创建', exact:true}).click()
  await stale.waitForFunction(() => window.uploadHarness.pending.createBankWithDocument?.length === 1)
  await stale.evaluate(() => {
    window.uploadHarness.generation++
    window.uploadHarness.finish('createBankWithDocument')
  })
  await stale.getByRole('button', {name:'创建', exact:true}).waitFor()
  assert.equal(await stale.evaluate(() => window.uploadHarness.changed), 0)
  assert.equal(await stale.evaluate(() => window.uploadHarness.closed), 0)
  assert.equal(await stale.evaluate(() => window.uploadHarness.calls.filter(call => call.name === 'uploadDocument').length), 0)
  passed.push('会话切换后停止后续上传并抑制旧会话回调')
  await stale.close()

  assert.deepEqual(runtimeErrors, [], '离线真实组件无未处理异常')
  console.log(JSON.stringify({passed:passed.length, cases:passed}, null, 2))
} finally {
  await browser.close()
}
