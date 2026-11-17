import katex from 'katex'
import { useMemo } from 'react'

function renderSegment(seg: string, display: boolean): string {
  try {
    return katex.renderToString(seg, { displayMode: display, throwOnError: false, output: 'html' })
  } catch {
    return seg
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** 转义后处理轻量 markdown：**粗体** 与换行保留，其余标记原样输出 */
function formatText(s: string): string {
  return escapeHtml(s).replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
}

/**
 * 常见数学命令名。用于两步判断：反斜杠后面跟的是 LaTeX 命令（而非普通文字），
 * 以及是不是被过度转义成了双反斜杠。
 */
const LATEX_COMMANDS = new Set([
  'neq', 'nabla', 'notin', 'ni', 'nu', 'nleq', 'ngeq', 'nsubseteq',
  'times', 'theta', 'tau', 'tan', 'text', 'textbf', 'textit', 'therefore', 'tilde',
  'frac', 'dfrac', 'tfrac', 'forall', 'flat',
  'rho', 'right', 'rightarrow', 'Rightarrow', 'rfloor', 'rceil', 'rangle',
  'beta', 'begin', 'end', 'bmatrix', 'Bmatrix', 'bigcup', 'bigcap', 'because',
  'boldsymbol', 'boxed', 'bullet', 'binom', 'bar',
  'alpha', 'approx', 'angle', 'ast', 'cdot', 'circ', 'cdots', 'cong', 'cos', 'cot',
  'csc', 'cap', 'cup', 'delta', 'displaystyle', 'div', 'ddots', 'ddot', 'dot',
  'equiv', 'exists', 'exp', 'varepsilon', 'varphi', 'vartheta',
  'gamma', 'geq', 'geqslant', 'gg', 'hat', 'hspace', 'infty', 'int', 'iint', 'iiint',
  'iota', 'kappa', 'lambda', 'langle', 'lceil', 'ldots', 'left', 'lfloor', 'lg',
  'lim', 'll', 'ln', 'log', 'leq', 'leqslant', 'lesssim', 'mathcal', 'mathbf',
  'mathbb', 'mathfrak', 'mathrm', 'mathsf', 'mathtt', 'mathop', 'operatorname',
  'max', 'min', 'mu', 'mp', 'odot', 'oint', 'oplus', 'otimes', 'omega', 'overline',
  'overbrace', 'partial', 'parallel', 'perp', 'phi', 'pi', 'pm', 'prod', 'propto',
  'psi', 'qquad', 'quad', 'sec', 'sigma', 'sim', 'simeq', 'sin', 'sqrt', 'star',
  'subset', 'subseteq', 'supset', 'supseteq', 'sum', 'textstyle', 'triangle',
  'underbrace', 'underline', 'uparrow', 'downarrow', 'upsilon', 'vec', 'vdots',
  'widehat', 'widetilde', 'xi', 'zeta', 'Delta', 'Lambda', 'Omega', 'Phi', 'Pi',
  'Psi', 'Sigma', 'Theta', 'Upsilon', 'Xi',
])

// JSON 转义里这几个控制字符会把命令首字母吃掉：\n→换行、\t→制表、\f→换页、\r→回车、\b→退格
const CONTROL_LEADS: Record<string, string> = {
  '\n': 'n',
  '\t': 't',
  '\f': 'f',
  '\r': 'r',
  '\b': 'b',
}

/** 预生成「控制字符 + 命令后缀 → \命令」，长串优先，避免前缀抢占 */
const CONTROL_REPAIRS: Array<[string, string]> = (() => {
  const pairs: Array<[string, string]> = []
  for (const command of LATEX_COMMANDS) {
    if (command.length < 3) continue // 两字母命令误判成本高，不做还原
    for (const [control, lead] of Object.entries(CONTROL_LEADS)) {
      if (command[0] === lead) pairs.push([control + command.slice(1), '\\' + command])
    }
  }
  return pairs.sort((a, b) => b[0].length - a[0].length)
})()

/**
 * 渲染前清洗。模型输出经过 JSON 序列化与 HTML 转义两道手，常见污染有三类：
 * 1 HTML 实体（&lt; &gt;）以字面形式残留；
 * 2 定界符被写成双反斜杠（\\[ \\] \\\( \\\)）；
 * 3 JSON 把单反斜杠当转义吃掉，\neq 变成换行加 eq、\frac 变成换页加 rac。
 * 后端入库前已修一遍，这里再兜一层，避免历史数据或跨端返回带病渲染。
 */
function preprocessLatex(input: string): string {
  if (!input) return input
  let text = input
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&') // 放最后，避免 &amp;lt; 被提前拆开
  text = text.replace(/\\\\([[\]()])/g, '\\$1')
  for (const [broken, fixed] of CONTROL_REPAIRS) {
    text = text.replace(new RegExp(broken + '(?![a-zA-Z])', 'g'), () => fixed)
  }
  // 奇数个反斜杠可能是矩阵换行后紧接命令，保留其行分隔。
  text = text.replace(/(\\{2,})([a-zA-Z]{2,})/g, (match, slashes: string, name: string) =>
    LATEX_COMMANDS.has(name) && slashes.length % 2 === 0 ? '\\' + name : match,
  )
  return text
}

/**
 * LaTeX 文本渲染组件。
 * 支持四种定界符：$...$（行内）、$$...$$（独立）、\(...\)（行内）、\[...\]（独立）。
 * 数学片段交给 KaTeX 渲染，其余纯文本转义输出（保留换行与 **粗体**）。
 */
export function Latex({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => {
    const source = preprocessLatex(text)
    const parts: string[] = []
    // 定界符按 display（$$、\[ \]）优先于 inline（\( \)、$）的顺序提取，避免交叉误判
    const regex = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$([^$\n]+?)\$/g
    let last = 0
    let m: RegExpExecArray | null
    while ((m = regex.exec(source)) !== null) {
      if (m.index > last) parts.push(formatText(source.slice(last, m.index)))
      if (m[1] !== undefined) parts.push(renderSegment(m[1], true))
      else if (m[2] !== undefined) parts.push(renderSegment(m[2], true))
      else parts.push(renderSegment(m[3] ?? m[4] ?? '', false))
      last = m.index + m[0].length
    }
    if (last < source.length) parts.push(formatText(source.slice(last)))
    return parts.join('')
  }, [text])
  return <span className={`whitespace-pre-wrap break-words${className ? ` ${className}` : ''}`} dangerouslySetInnerHTML={{ __html: html }} />
}
