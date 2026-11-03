/** 文档上传与入库进度：真实上传 + 轮询后端解析/向量化状态。 */
import { useRef, useState } from 'react'
import * as bankApi from '../../../api/banks'
import type { BankDoc } from '../../../api/banks'

export interface UploadState {
  name: string
  phase: 'upload' | 'vector' | 'done'
  pct: number
  stage?: string
}

export function useDocUpload(bankId: string, onFinished: (doc: BankDoc) => void, notify: (msg: string) => void) {
  const [upload, setUpload] = useState<UploadState | null>(null)
  const busy = useRef(false)

  const start = (file: File) => {
    if (busy.current) return
    busy.current = true
    setUpload({ name: file.name, phase: 'upload', pct: 0 })
    void bankApi
      .uploadAndWait(bankId, file, (phase, pct, stage) => setUpload({ name: file.name, phase, pct, stage }))
      .then((doc) => {
        onFinished(doc)
        notify(`「${file.name}」已上传并完成入库`)
      })
      .catch((err) => {
        notify(err instanceof Error ? err.message : '上传失败')
      })
      .finally(() => {
        busy.current = false
        window.setTimeout(() => setUpload(null), 500)
      })
  }

  return { upload, start }
}
