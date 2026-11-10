/* global URL, console, process, window, document, Response, ReadableStream, TextEncoder, getComputedStyle */
/** 离线预览回归：打包真实组件、会话与 API；浏览器 HTTP 全部由内存夹具响应。 */
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { createRequire } from 'node:module'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'

const require = createRequire(join(tmpdir(), 'mathcraft-auth-browser', 'package.json'))
const { chromium } = require('playwright-core')
// 可由浏览器原生 PDF 阅读器解析的一页 PDF，避免用损坏文件掩盖 Blob 显示路径。
function pdfFixture() {
  const content = 'BT /F1 18 Tf 40 100 Td (Offline PDF preview) Tj ET\n'
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}endstream`,
  ]
  let pdf = '%PDF-1.4\n'
  const offsets = []
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf))
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
  }
  const xref = Buffer.byteLength(pdf)
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.map(offset => String(offset).padStart(10, '0') + ' 00000 n \n').join('')}`
  return Buffer.from(pdf + `trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`)
}
const pdfBytes = pdfFixture()
const bundle = await build({
  stdin: { contents: `
    import React, {useState} from 'react';
    import {createRoot} from 'react-dom/client';
    import * as api from './src/api/backend';
    import * as session from './src/api/session';
    import DocPreviewModal from './src/components/tabs/BankTab/DocPreviewModal';
    const h = window.previewHarness;
    Object.assign(h, {api, session});
    session.setApiToken('fake-preview-token');
    function Harness() {
      const [props, setProps] = useState(null);
      h.show = props => setProps({bankId:'bank', docId:'doc', docName:'合成文档', ...props});
      h.hide = () => setProps(null);
      return <><button id="opener" onClick={() => h.show({})}>打开预览</button>
        {props && <DocPreviewModal {...props} onClose={() => {h.closed++; setProps(null)}}/>}</>;
    }
    createRoot(document.getElementById('root')).render(<Harness/>);
  `, resolveDir: fileURLToPath(new URL('.', import.meta.url)), loader: 'jsx' },
  bundle: true, write: false, format: 'iife', jsx: 'automatic',
  define: { 'import.meta.env': '{}', 'process.env.NODE_ENV': '"development"' },
})
const browser = await chromium.launch({ executablePath: process.env.AUTH_BROWSER ?? join(
  homedir(), 'AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe',
), headless: true })
const failures = []
let passed = 0
const filter = process.argv.slice(2).join(' ')

async function test(name, action) {
  if (filter && !name.includes(filter)) return
  const context = await browser.newContext({ acceptDownloads: true })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const fixture = { type: 'text/plain; charset=utf-8', body: '# 标题\n\n$x+1$', status: 200, calls: [] }
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url())
    if (url.origin !== 'http://document-preview.test') return route.abort()
    if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="root"></div>' })
    fixture.calls.push({ url: url.href, authorization: request.headers().authorization })
    await route.fulfill({ status: fixture.status, contentType: fixture.type, body: fixture.body })
  })
  try {
    await page.goto('http://document-preview.test/')
    await page.evaluate(() => {
      const h = window.previewHarness = { closed: 0, created: [], revoked: [], textReads: 0, deadlines: new Map(), events: [] }
      const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL)
      URL.createObjectURL = blob => { const url = create(blob); h.created.push({ url, type: blob.type, size: blob.size }); return url }
      URL.revokeObjectURL = url => { h.revoked.push(url); revoke(url) }
      const text = Response.prototype.text
      Response.prototype.text = function () { h.textReads++; return text.call(this) }
      const setTimeout = window.setTimeout.bind(window), clearTimeout = window.clearTimeout.bind(window)
      window.setTimeout = (action, delay, ...args) => {
        if (delay !== 60_000 && delay !== 180_000) return setTimeout(action, delay, ...args)
        const id = setTimeout(() => {}, 3_600_000)
        h.deadlines.set(id, { action, delay })
        return id
      }
      window.clearTimeout = id => { h.deadlines.delete(id); clearTimeout(id) }
      h.expire = delay => { for (const timer of [...h.deadlines.values()]) if (timer.delay === delay) timer.action() }
      const open = window.open.bind(window)
      window.open = (...args) => { h.events.push('open'); h.popup = open(...args); return h.popup }
      const fetch = window.fetch.bind(window)
      h.nativeFetch = fetch
      window.fetch = (...args) => { h.events.push('fetch'); return fetch(...args) }
      h.stream = (chunks, type = 'text/plain', complete = false, length) => {
        h.streamCancelled = false
        window.fetch = async (_url, init) => {
          h.signal = init.signal
          let streamController
          init.signal?.addEventListener('abort', () => { h.aborted = true; streamController.error(init.signal.reason) }, {once:true})
          const headers = { 'Content-Type': type }
          if (length !== undefined) headers['Content-Length'] = String(length)
          h.response = new Response(new ReadableStream({
            start(controller) {
              h.streamController = streamController = controller
              for (const chunk of chunks) controller.enqueue(typeof chunk === 'string' ? new TextEncoder().encode(chunk) : new Uint8Array(chunk))
              if (complete) controller.close()
            },
            cancel() { h.streamCancelled = true },
          }), { headers })
          return h.response
        }
      }
      h.holdHeaders = () => {
        window.fetch = (_url, init) => {
          h.signal = init.signal
          return new Promise((_resolve, reject) => {
            init.signal.addEventListener('abort', () => { h.aborted = true; reject(init.signal.reason) }, {once:true})
          })
        }
      }
      h.openPdf = () => {
        h.pdfState = 'pending'
        const promise = h.api.openPdfDocument('bank', 'doc')
        h.openedSynchronously = h.events[0] === 'open'
        promise.then(() => { h.pdfState = 'resolved' }, error => { h.pdfState = 'rejected'; h.pdfError = error.message })
      }
    })
    await page.addScriptTag({ content: bundle.outputFiles[0].text })
    await page.waitForFunction(() => window.previewHarness.show)
    await action({ page, context, fixture })
    assert.deepEqual(errors, [], '浏览器不得出现未处理异常')
    for (const call of fixture.calls) {
      assert.equal(call.authorization, 'Bearer fake-preview-token', '下载必须沿用 sessionFetch 认证')
      assert.ok(!call.url.includes('token'), '认证凭据不得进入 URL')
    }
    passed++
    console.log('PASS:', name)
  } catch (error) {
    failures.push(name)
    console.error('FAIL:', name, '\n ', error.message)
  } finally { await context.close() }
}

try {
  await test('TXT 保留 Markdown 和公式源码，不调用 KaTeX', async ({ page, fixture }) => {
    fixture.body = '# 纯文本\n\n**不是粗体** $x$ <script>危险</script>'
    await page.evaluate(() => window.previewHarness.show({ docFormat: 'TXT' }))
    await page.getByText('**不是粗体** $x$ <script>危险</script>', { exact: false }).waitFor({ timeout: 3000 })
    assert.equal(await page.locator('.katex').count(), 0)
    assert.equal(await page.getByRole('heading', { name: '纯文本', exact: true }).count(), 0)
  })
  await test('二进制 Content-Type 被拒绝并提供重试和下载', async ({ page, fixture }) => {
    fixture.type = 'application/pdf'; fixture.body = '%PDF-1.7 synthetic'
    await page.evaluate(() => window.previewHarness.show({}))
    await page.getByRole('alert').waitFor({ timeout: 3000 })
    assert.equal(await page.getByRole('button', { name: '重试预览' }).count(), 1)
    assert.equal(await page.getByRole('button', { name: '下载文档' }).count(), 1)
    assert.equal(await page.evaluate(() => window.previewHarness.textReads), 0)
  })
  await test('Markdown 每页最多 40 块，仅当前页渲染公式', async ({ page, fixture }) => {
    fixture.body = Array.from({ length: 81 }, (_, i) => `段落${i} $x_${i}$`).join('\n\n')
    await page.evaluate(() => window.previewHarness.show({}))
    await page.locator('.katex').first().waitFor()
    assert.equal(await page.locator('.katex').count(), 40)
    await page.getByRole('button', { name: '下一页' }).click()
    assert.equal(await page.locator('.katex').count(), 40)
    assert.equal(await page.getByText('段落0 ', { exact: false }).count(), 0)
  })
  await test('PDF 在异步请求前同步开窗', async ({ page, fixture }) => {
    fixture.type = 'application/pdf'; fixture.body = pdfBytes
    await page.evaluate(() => window.previewHarness.openPdf())
    assert.equal(await page.evaluate(() => window.previewHarness.openedSynchronously), true)
    await page.waitForFunction(() => window.previewHarness.pdfState !== 'pending')
    assert.equal(await page.evaluate(() => window.previewHarness.textReads), 0)
  })
  await test('文本 2 MiB 边界、UTF-8 跨块解码、无 Content-Length 的流式超限', async ({ page }) => {
    const result = await page.evaluate(async () => {
      const h = window.previewHarness
      h.stream([[0xe4], [0xb8, 0xad]], 'text/markdown; charset="UTF-8"', true)
      const unicode = await h.api.fetchDocumentText('bank', 'doc')
      h.stream(['a'.repeat(2 * 1024 * 1024)], 'text/plain', true)
      const boundary = (await h.api.fetchDocumentText('bank', 'doc')).length
      h.stream(['a'.repeat(2 * 1024 * 1024), 'b'])
      let error
      try { await h.api.fetchDocumentText('bank', 'doc') } catch (failure) { error = failure.code }
      return { unicode, boundary, error, cancelled: h.streamCancelled, textReads: h.textReads }
    })
    assert.deepEqual(result, { unicode: '中', boundary: 2 * 1024 * 1024, error: 'DOCUMENT_TOO_LARGE', cancelled: true, textReads: 0 })
  })
  await test('声明超限、错误 MIME、非 UTF-8 与非法 UTF-8 不得继续读取', async ({ page }) => {
    const result = await page.evaluate(async () => {
      const h = window.previewHarness, errors = []
      for (const [chunks, type, length, format] of [
        [[], 'text/plain', 2 * 1024 * 1024 + 1, 'MD'],
        [[], 'application/octet-stream', undefined, 'MD'],
        [[], 'text/markdown', undefined, 'TXT'],
        [[], 'text/plain; charset=gbk', undefined, 'TXT'],
        [[[0xff]], 'text/plain', undefined, 'TXT'],
      ]) {
        h.stream(chunks, type, false, length)
        try { await h.api.fetchDocumentText('bank', 'doc', undefined, format) }
        catch (error) { errors.push(Boolean(error.message)) }
      }
      return { errors, textReads: h.textReads }
    })
    assert.deepEqual(result, { errors: [true, true, true, true, true], textReads: 0 })
  })
  for (const phase of ['headers', 'body']) {
    await test(`文本 60 秒超时覆盖 ${phase}，红色错误后可重试`, async ({ page, fixture }) => {
      await page.evaluate(phase => {
        const h = window.previewHarness
        if (phase === 'headers') h.holdHeaders()
        else h.stream(['部分内容'])
        h.show({})
      }, phase)
      await page.waitForFunction(() => window.previewHarness.signal)
      await page.getByRole('status').filter({ hasText: '正在载入文档' }).waitFor()
      await page.evaluate(() => window.previewHarness.expire(60_000))
      await page.getByRole('alert').filter({ hasText: '60 秒' }).waitFor()
      assert.equal(await page.evaluate(() => window.previewHarness.signal.aborted), true)
      fixture.body = '# 重试成功'
      await page.evaluate(() => { window.fetch = (...args) => window.previewHarness.nativeFetch(...args) })
      await page.getByRole('button', { name: '重试预览' }).click()
      await page.getByRole('heading', { name: '重试成功', exact: true }).waitFor()
    })
  }
  for (const action of ['close', 'switch', 'session']) {
    await test(`文本 ${action} 取消底层读取且不展示错误`, async ({ page }) => {
      await page.evaluate(() => { const h = window.previewHarness; h.stream(['旧文档']); h.show({}) })
      await page.waitForFunction(() => window.previewHarness.signal)
      await page.evaluate(() => { window.previewHarness.oldSignal = window.previewHarness.signal })
      if (action === 'close') await page.getByRole('button', { name: '关闭文档预览' }).click()
      if (action === 'session') await page.evaluate(() => window.previewHarness.session.clearSession(false))
      if (action === 'switch') {
        await page.evaluate(() => {
          const h = window.previewHarness
          h.stream(['新文档正文'], 'text/plain', true)
          h.show({ docId: 'new', docName: '新文档', docFormat: 'TXT' })
        })
        await page.getByText('新文档正文', { exact: true }).waitFor()
        assert.equal(await page.getByText('旧文档', { exact: true }).count(), 0)
      } else await page.getByRole('dialog').waitFor({ state: 'detached' })
      assert.equal(await page.evaluate(() => window.previewHarness.oldSignal.aborted), true)
      await page.waitForFunction(() => !window.previewHarness.response.body.locked, null, { timeout: 2000 })
      assert.equal(await page.getByRole('alert').count(), 0)
    })
  }
  await test('Markdown 字符预算和超大公式块降级，不渲染截断公式', async ({ page, fixture }) => {
    fixture.body = `第一块${'a'.repeat(11_000)}\n\n第二块${'b'.repeat(11_000)}\n\n$$\n${'x'.repeat(20_001)}\n$$`
    await page.evaluate(() => window.previewHarness.show({}))
    await page.getByText('第 1 / 3 页', { exact: true }).waitFor()
    assert.equal(await page.getByText(/^第二块/).count(), 0)
    await page.getByRole('button', { name: '下一页' }).click()
    await page.getByText(/^第二块/).waitFor()
    await page.getByRole('button', { name: '下一页' }).click()
    assert.equal((await page.locator('pre').innerText()).length, 20_000)
    assert.equal(await page.locator('.katex').count(), 0)
    await page.getByRole('status').filter({ hasText: '已按纯文本截断' }).waitFor()
    assert.equal(await page.getByRole('button', { name: '下载文档' }).count(), 1)
  })
  await test('分页按钮可用键盘，焦点受限于弹窗，Escape 关闭并还原焦点', async ({ page, fixture }) => {
    fixture.body = Array.from({ length: 41 }, (_, i) => `段${i}`).join('\n\n')
    await page.getByRole('button', { name: '打开预览' }).click()
    await page.getByText('第 1 / 2 页', { exact: true }).waitFor()
    await page.getByRole('button', { name: '下一页' }).focus()
    await page.keyboard.press('Enter')
    await page.getByText('第 2 / 2 页', { exact: true }).waitFor()
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute('aria-label')), '文档预览内容')
    await page.getByRole('button', { name: '上一页' }).focus()
    await page.keyboard.press('Tab')
    assert.equal(await page.evaluate(() => document.activeElement.textContent), '下载文档')
    await page.keyboard.press('Shift+Tab')
    assert.equal(await page.evaluate(() => document.activeElement.textContent), '上一页')
    await page.keyboard.press('Escape')
    await page.getByRole('dialog').waitFor({ state: 'detached' })
    assert.equal(await page.evaluate(() => document.activeElement.id), 'opener')
  })
  await test('文本 HTTP 错误可重试，空文档仍可认证下载', async ({ page, fixture }) => {
    fixture.status = 503
    await page.evaluate(() => window.previewHarness.show({ docName: 'empty.txt', docFormat: 'TXT' }))
    await page.getByRole('alert').filter({ hasText: 'HTTP 503' }).waitFor()
    fixture.status = 200; fixture.body = ''
    await page.getByRole('button', { name: '重试预览' }).click()
    await page.getByText('文档暂无可预览内容', { exact: true }).waitFor()
    const downloaded = page.waitForEvent('download')
    await page.getByRole('button', { name: '下载文档' }).click()
    assert.equal((await downloaded).suggestedFilename(), 'empty.txt')
    assert.equal(new URL(fixture.calls.at(-1).url).search, '')
    assert.equal(await page.evaluate(() => window.previewHarness.created.length === window.previewHarness.revoked.length), true)
  })
  await test('不支持的文本格式拒绝请求，并保留下载入口', async ({ page, fixture }) => {
    await page.evaluate(() => window.previewHarness.show({ docFormat: 'DOCX' }))
    await page.getByRole('alert').filter({ hasText: '不支持文本预览' }).waitFor()
    assert.equal(fixture.calls.length, 0)
    assert.equal(await page.getByRole('button', { name: '下载文档' }).count(), 1)
  })
  await test('PDF 弹窗拦截立即拒绝且不发起下载请求', async ({ page, fixture }) => {
    await page.evaluate(() => { window.open = () => null; window.previewHarness.openPdf() })
    await page.waitForFunction(() => window.previewHarness.pdfState === 'rejected')
    assert.match(await page.evaluate(() => window.previewHarness.pdfError), /拦截.*重试.*下载/)
    assert.equal(fixture.calls.length, 0)
  })
  for (const action of ['close', 'session']) {
    await test(`PDF 成功显示 Blob，${action} 回收 URL`, async ({ page, fixture }) => {
      fixture.type = 'application/pdf'; fixture.body = pdfBytes
      await page.evaluate(() => window.previewHarness.openPdf())
      await page.waitForFunction(() => window.previewHarness.pdfState === 'resolved')
      const result = await page.evaluate(async () => {
        const h = window.previewHarness
        const blobResponse = await h.nativeFetch(h.created[0].url)
        return { type: h.created[0].type, src: h.popup.document.querySelector('iframe').getAttribute('src'),
          url: h.popup.location.href, opener: h.popup.opener, textReads: h.textReads,
          bytes: [...new Uint8Array(await blobResponse.arrayBuffer())] }
      })
      assert.equal(result.type, 'application/pdf')
      assert.match(result.src, /^blob:/)
      assert.equal(result.url, 'about:blank')
      assert.equal(result.opener, null)
      assert.equal(result.textReads, 0)
      assert.deepEqual(result.bytes, [...pdfBytes])
      await page.evaluate(action => {
        const h = window.previewHarness
        if (action === 'close') h.popup.close()
        else h.session.clearSession(false)
      }, action)
      await page.waitForFunction(() => window.previewHarness.revoked.length === 1)
      assert.equal(await page.evaluate(() => window.previewHarness.popup.closed), true)
    })
  }
  for (const phase of ['headers', 'body']) {
    await test(`PDF 180 秒超时覆盖 ${phase}，窗口红提示并可重试`, async ({ page, context, fixture }) => {
      await page.evaluate(phase => {
        const h = window.previewHarness
        if (phase === 'headers') h.holdHeaders()
        else h.stream(['%PDF partial'], 'application/pdf')
        h.openPdf()
      }, phase)
      await page.waitForFunction(() => window.previewHarness.signal)
      await page.evaluate(() => window.previewHarness.expire(180_000))
      await page.waitForFunction(() => window.previewHarness.pdfState === 'rejected')
      const popup = context.pages().find(candidate => candidate !== page)
      await popup.getByRole('alert').filter({ hasText: '180 秒' }).waitFor()
      assert.equal(await popup.getByRole('alert').evaluate(element => getComputedStyle(element).color), 'rgb(185, 28, 28)')
      fixture.type = 'application/pdf'; fixture.body = pdfBytes
      await page.evaluate(() => { window.fetch = window.previewHarness.nativeFetch })
      await popup.getByRole('button', { name: '重试预览' }).click()
      await page.waitForFunction(() => window.previewHarness.created.length === 1)
      assert.equal(await page.evaluate(() => window.previewHarness.textReads), 0)
    })
  }
  for (const action of ['close', 'session']) {
    await test(`PDF 请求中 ${action} 静默取消，无残留 URL`, async ({ page }) => {
      await page.evaluate(() => { const h = window.previewHarness; h.stream(['%PDF'], 'application/pdf'); h.openPdf() })
      await page.waitForFunction(() => window.previewHarness.signal)
      await page.evaluate(action => {
        const h = window.previewHarness
        if (action === 'close') h.popup.close()
        else h.session.clearSession(false)
      }, action)
      await page.waitForFunction(() => window.previewHarness.pdfState === 'resolved')
      assert.equal(await page.evaluate(() => window.previewHarness.signal.aborted), true)
      assert.equal(await page.evaluate(() => window.previewHarness.created.length), 0)
    })
  }
  await test('PDF MIME 和 HTTP 失败保持红提示，下载按钮可恢复', async ({ page, context, fixture }) => {
    fixture.type = 'text/html'; fixture.body = '<h1>错误页面</h1>'
    await page.evaluate(() => window.previewHarness.openPdf())
    await page.waitForFunction(() => window.previewHarness.pdfState === 'rejected')
    const popup = context.pages().find(candidate => candidate !== page)
    await popup.getByRole('alert').filter({ hasText: '不是 PDF' }).waitFor()
    fixture.status = 404
    await popup.getByRole('button', { name: '重试预览' }).click()
    await popup.getByRole('alert').filter({ hasText: 'HTTP 404' }).waitFor()
    fixture.status = 200; fixture.type = 'application/pdf'; fixture.body = pdfBytes
    const downloaded = page.waitForEvent('download')
    await popup.getByRole('button', { name: '下载文档' }).click()
    assert.equal((await downloaded).suggestedFilename(), 'document-doc.pdf')
    assert.equal(await page.evaluate(() => window.previewHarness.textReads), 0)
    assert.equal(new URL(fixture.calls.at(-1).url).search, '')
  })
} finally { await browser.close() }
console.log(`预览回归：${passed} 通过，${failures.length} 失败`)
if (failures.length) process.exitCode = 1
