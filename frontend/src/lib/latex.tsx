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

/**
 * LaTeX 文本渲染组件。
 * 将文本按 $...$（行内）与 $$...$$（独立成行）分段，
 * 数学片段交给 KaTeX 渲染，其余按纯文本转义输出。
 * 支持矩阵、积分、求和等 KaTeX 全部语法。
 */
export function Latex({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => {
    const parts: string[] = []
    const regex = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g
    let last = 0
    let m: RegExpExecArray | null
    while ((m = regex.exec(text)) !== null) {
      if (m.index > last) parts.push(escapeHtml(text.slice(last, m.index)))
      if (m[1] !== undefined) parts.push(renderSegment(m[1], true))
      else parts.push(renderSegment(m[2] ?? '', false))
      last = m.index + m[0].length
    }
    if (last < text.length) parts.push(escapeHtml(text.slice(last)))
    return parts.join('')
  }, [text])
  return <span className={className} dangerouslySetInnerHTML={{ __html: html }} />
}
