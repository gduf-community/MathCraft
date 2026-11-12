/** 导出 Word 文档：把已生成题目按题型分组输出为 .docx。 */
import { authenticatedOperation } from './session'
import { apiUrl } from './urls'
import { ApiError } from './backend'
import type { Question, QuestionType } from '../types'

export interface ExportDocxPayload {
  title: string
  include_answer: boolean
  include_analysis: boolean
  /** inline=答案解析在每题下方 end=集中在文末 */
  placement: 'inline' | 'end'
  type_order: QuestionType[]
  questions: {
    type: QuestionType
    score: number
    difficulty: string
    stem: string
    options: { label: string; text: string }[]
    answer: string
    analysis: string
    knowledge_point?: string
  }[]
}

function payloadFromQuestion(q: Question): ExportDocxPayload['questions'][number] {
  return {
    type: q.type,
    score: q.score,
    difficulty: q.difficulty,
    stem: q.stem,
    options: q.options,
    answer: q.answer,
    analysis: q.analysis,
    knowledge_point: q.knowledgePoint,
  }
}

/** 请求导出并把返回的 docx Blob 触发浏览器下载。 */
export async function exportQuestionsDocx(
  title: string,
  includeAnswer: boolean,
  includeAnalysis: boolean,
  placement: 'inline' | 'end',
  typeOrder: QuestionType[],
  questions: Question[],
): Promise<void> {
  const body: ExportDocxPayload = {
    title,
    include_answer: includeAnswer,
    include_analysis: includeAnalysis,
    placement,
    type_order: typeOrder,
    questions: questions.map(payloadFromQuestion),
  }
  await authenticatedOperation(async (token) => {
    const response = await fetch(apiUrl('/api/export/docx'), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      let message = `导出失败（HTTP ${response.status}）`
      try {
        const detail = (await response.json())?.detail
        if (detail && typeof detail.message === 'string') message = detail.message
      } catch { /* 保留默认文案 */ }
      throw new ApiError(message, 'EXPORT_FAILED', response.status)
    }
    const blob = await response.blob()
    const disposition = response.headers.get('Content-Disposition') ?? ''
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/)?.[1]
    const filename = encoded ? decodeURIComponent(encoded) : `${title}.docx`
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  })
}
