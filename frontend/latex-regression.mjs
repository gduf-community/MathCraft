import assert from 'node:assert/strict'
import console from 'node:console'
import { createRequire } from 'node:module'
import { fileURLToPath, URL } from 'node:url'
import { runInNewContext } from 'node:vm'
import { build } from 'esbuild'
import katex from 'katex'

const bundle = await build({
  stdin: {
    contents: `import {renderToStaticMarkup} from 'react-dom/server';
      import {Latex} from './src/lib/latex';
      export const render = text => renderToStaticMarkup(<Latex text={text}/>);`,
    resolveDir: fileURLToPath(new URL('.', import.meta.url)),
    loader: 'tsx',
  },
  bundle: true,
  packages: 'external',
  platform: 'node',
  format: 'cjs',
  jsx: 'automatic',
  write: false,
})
const compiled = { exports: {} }
runInNewContext(bundle.outputFiles[0].text, {
  module: compiled,
  exports: compiled.exports,
  require: createRequire(import.meta.url),
})
const { render } = compiled.exports
for (const text of [String.raw`\\[x\\]`, String.raw`\\(x\\)`]) {
  const html = render(text)
  assert.ok(html.includes('class="katex'), text)
  assert.ok(!html.includes('katex-error'), text)
}
for (const word of ['equation', 'imescale', 'riangleword']) {
  const text = `说明\n${word}`
  assert.ok(render(text).includes(text), word)
}
const repaired = render('$a\neq b$')
assert.equal(repaired, render(String.raw`$a\neq b$`))
assert.ok(!repaired.includes('katex-error'))
const matrixBody = String.raw`\begin{pmatrix}1\\\frac{1}{2}\end{pmatrix}`
const matrix = render(`$${matrixBody}$`)
assert.ok(!matrix.includes('katex-error'))
assert.equal((matrix.match(/class="mfrac"/g) ?? []).length, 1)
assert.ok(matrix.includes('mtable'))
assert.ok(matrix.includes(katex.renderToString(matrixBody, {
  displayMode: false, throwOnError: true, output: 'html',
})))
console.log('PASS 公式历史定界、控制字符边界与矩阵换行回归')
