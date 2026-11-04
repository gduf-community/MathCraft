import { useRef, useState } from 'react'
import type { Question } from '../../../types'
import { readSavedQuestion } from '../../../api/httpAdapter'
import { apiUrl } from '../../../api/urls'

const RELATION = { original: '原题', variant_reference: '变式参考', concept_reference: '考点参考' }

export default function SourcePanel({ question }: { question: Question }) {
  const [current, setCurrent] = useState(question)
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)
  const latestRequest = useRef(0)
  const sources = current.sources ?? []
  return <details aria-busy={checking} className="mt-3 rounded border border-line p-3 text-sm" onToggle={(event) => {
    if (event.target !== event.currentTarget) return
    if (event.currentTarget.open && question.sources?.length) {
      const request = ++latestRequest.current
      setError('')
      setChecking(true)
      void readSavedQuestion(question.id)
        .then((saved) => {
          if (request === latestRequest.current) setCurrent(saved)
        })
        .catch(() => {
          if (request === latestRequest.current) setError('来源状态暂时无法刷新，请稍后重试。')
        })
        .finally(() => {
          if (request === latestRequest.current) setChecking(false)
        })
    }
  }}>
    <summary className="cursor-pointer">来源与审核状态</summary>
    <p className="mt-2">{question.review_status === 'edited_requires_review' ? '数学内容已编辑，需重新审核' : question.review_status === 'unreviewed' ? '生成结果尚未经过数学复核' : '旧题审核状态未知'}</p>
    {error && <p role="alert">{error}</p>}
    {!sources.length && <p>来源未知：此题没有可验证的逐题证据记录。</p>}
    {sources.map((source) => <section key={source.evidence_id} className="mt-3 border-t border-line pt-2">
      <p>{RELATION[source.relation]} · {source.document_key} · {source.evidence_id}</p>
      <p>索引 {source.index_version || '未知'} · PDF 页 {source.page_indices.length ? source.page_indices.map((p) => p + 1).join('、') : '未知 / 不适用'}</p>
      <p>来源：{checking ? '正在核对来源' : error ? '未验证（本次刷新失败）' : source.source_status === 'valid' ? '文件身份有效' : source.source_status === 'changed' ? '原文件已变化，不能用当前文件替代旧证据' : source.source_status === 'missing' ? '原文件已删除或不可用' : '未验证'}</p>
      <p>证据完整性：{source.completeness === 'complete' ? '原文单元已完整传递' : '未确认完整'}</p>
      <p>解析产物检查：{source.quality_status === 'passed' ? '通过' : source.quality_status === 'warning' ? '有使用限制' : source.quality_status === 'failed' ? '未通过' : '未知，重建后可重新检查'}{source.quality_policy ? `（${source.quality_policy}）` : ''}；不代表数学已复核</p>
      {source.warnings.map((warning) => <p key={warning}>{warning}</p>)}
      {!checking && !error && source.source_status === 'valid' && <div className="flex flex-wrap gap-3 text-primary">
        <a href={apiUrl(source.file_url)} target="_blank" rel="noreferrer">原文件</a>
        {source.source_page_urls.map((url, i) => <a key={url} href={apiUrl(url)} target="_blank" rel="noreferrer">原页 {source.page_indices[i] + 1}</a>)}
        {source.image_urls.map((url, i) => <a key={url} href={apiUrl(url)} target="_blank" rel="noreferrer">图片 {i + 1}</a>)}
      </div>}
      <details className="mt-2"><summary>本题参考原文</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words font-sans">{source.evidence_text}</pre></details>
    </section>)}
  </details>
}
