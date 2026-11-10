/** 预览分页仅处理文本；公式组件只挂载当前页。 */
import type { TextDocumentFormat } from '../../../api/documentPreview'

const PAGE_BLOCK_LIMIT = 40
const PAGE_CHARACTER_LIMIT = 20_000
type Block =
  | { kind: 'h'; level: number; text: string }
  | { kind: 'p' | 'quote' | 'math' | 'plain'; text: string }
  | { kind: 'li'; text: string; depth: number }
  | { kind: 'hr'; text: string }

export type DocumentPreviewBlock = Block & { id: number; truncated: boolean }

function parseMarkdown(text: string): Block[] {
  const blocks: Block[] = []
  let math: string[] | null = null
  let paragraph: string[] = []
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: 'p', text: paragraph.join(' ') })
    paragraph = []
  }
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trimEnd()
    if (math !== null) {
      if (line.trim() === '$$') {
        blocks.push({ kind: 'math', text: math.join('\n') })
        math = null
      } else math.push(raw)
      continue
    }
    if (line.trim() === '$$') { flush(); math = []; continue }
    if (!line.trim()) { flush(); continue }
    if (/^-{3,}$/.test(line.trim())) { flush(); blocks.push({ kind: 'hr', text: '' }); continue }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      flush()
      blocks.push({ kind: 'h', level: heading[1].length, text: heading[2].trim() })
      continue
    }
    if (/^>\s?/.test(line)) {
      flush()
      blocks.push({ kind: 'quote', text: line.replace(/^>\s?/, '') })
      continue
    }
    const item = /^(\s*)[-*]\s+(.*)$/.exec(line)
    if (item) {
      flush()
      blocks.push({ kind: 'li', depth: Math.min(3, Math.floor(item[1].length / 2)), text: item[2].trim() })
      continue
    }
    paragraph.push(line.trim())
  }
  flush()
  if (math !== null) blocks.push({ kind: 'math', text: math.join('\n') })
  return blocks
}

/** 避免分页或截断从 UTF-16 代理对中间切开。 */
function textPrefix(text: string, limit: number): string {
  const last = text.charCodeAt(limit - 1)
  return text.slice(0, last >= 0xd800 && last <= 0xdbff ? limit - 1 : limit)
}

/** MD 每页至多 40 块和 2 万字符；超长单块退化为截断纯文本。TXT 保留源码。 */
export function buildDocumentPreviewPages(text: string, format: TextDocumentFormat): DocumentPreviewBlock[][] {
  let parsed: Block[]
  if (format === 'TXT') {
    parsed = []
    let offset = 0
    while (offset < text.length) {
      const part = textPrefix(text.slice(offset), PAGE_CHARACTER_LIMIT)
      parsed.push({ kind: 'plain', text: part })
      offset += part.length
    }
  } else parsed = parseMarkdown(text)
  const pages: DocumentPreviewBlock[][] = []
  let page: DocumentPreviewBlock[] = []
  let characters = 0
  for (const [id, block] of parsed.entries()) {
    const truncated = block.text.length > PAGE_CHARACTER_LIMIT
    const bounded: DocumentPreviewBlock = truncated
      ? { id, kind: 'plain', text: textPrefix(block.text, PAGE_CHARACTER_LIMIT), truncated }
      : { ...block, id, truncated }
    const length = Math.max(1, bounded.text.length)
    if (page.length && (page.length >= PAGE_BLOCK_LIMIT || characters + length > PAGE_CHARACTER_LIMIT)) {
      pages.push(page)
      page = []
      characters = 0
    }
    page.push(bounded)
    characters += length
  }
  if (page.length) pages.push(page)
  return pages
}
