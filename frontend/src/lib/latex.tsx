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
 * LaTeX 文本渲染组件。
 * 支持四种定界符：$...$（行内）、$$...$$（独立）、\(...\)（行内）、\[...\]（独立）。
 * 数学片段交给 KaTeX 渲染，其余纯文本转义输出（保留换行与 **粗体**）。
 */
export function Latex({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => {
    const parts: string[] = []
    // 定界符按 display（$$、\[ \]）优先于 inline（\( \)、$）的顺序提取，避免交叉误判
    const regex = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$([^$\n]+?)\$/g
    let last = 0
    let m: RegExpExecArray | null
    while ((m = regex.exec(text)) !== null) {
      if (m.index > last) parts.push(formatText(text.slice(last, m.index)))
      if (m[1] !== undefined) parts.push(renderSegment(m[1], true))
      else if (m[2] !== undefined) parts.push(renderSegment(m[2], true))
      else parts.push(renderSegment(m[3] ?? m[4] ?? '', false))
      last = m.index + m[0].length
    }
    if (last < text.length) parts.push(formatText(text.slice(last)))
    return parts.join('')
  }, [text])
  return <span className={`whitespace-pre-wrap break-words${className ? ` ${className}` : ''}`} dangerouslySetInnerHTML={{ __html: html }} />
}
