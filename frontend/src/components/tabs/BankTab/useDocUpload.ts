/** 文档上传进度模拟 hook：上传 → 向量化 → 完成入列，供编辑/查看弹窗共用。
 * 进度状态放在 ref 里驱动，避免 setState updater 双调用导致重复入库（StrictMode）。 */
import { useRef, useState } from 'react'
import * as bankMock from '../../../api/mock/bankMock'
import type { BankDoc } from '../../../api/mock/bankMock'

export interface UploadState {
  name: string
  phase: 'upload' | 'vector' | 'done'
  pct: number
}

const FORMATS = ['PDF', 'DOCX', 'XLSX', 'MD']
const fmtOf = (name: string) => {
  const ext = name.split('.').pop()?.toUpperCase() ?? 'PDF'
  return FORMATS.includes(ext) ? ext : 'PDF'
}

export function useDocUpload(bankId: string, onFinished: (doc: BankDoc) => void, notify: (msg: string) => void) {
  const [upload, setUpload] = useState<UploadState | null>(null)
  const state = useRef<UploadState | null>(null)

  const start = (name: string, size: string) => {
    if (state.current) return
    const format = fmtOf(name)
    state.current = { name, phase: 'upload', pct: 0 }
    setUpload({ ...state.current })
    const iv = window.setInterval(() => {
      const u = state.current
      if (!u) {
        clearInterval(iv)
        return
      }
      if (u.phase === 'upload') {
        u.pct = Math.min(100, u.pct + 8 + Math.random() * 10)
        if (u.pct >= 100) {
          u.phase = 'vector'
          u.pct = 0
        }
      } else if (u.phase === 'vector') {
        u.pct = Math.min(100, u.pct + 6 + Math.random() * 9)
        if (u.pct >= 100) {
          u.phase = 'done'
          u.pct = 100
          clearInterval(iv)
          void bankMock
            .addDoc(bankId, name, format, size)
            .then((doc) => onFinished(doc))
            .then(() => notify(`「${name}」上传完成，已加入题库`))
          window.setTimeout(() => {
            state.current = null
            setUpload(null)
          }, 500)
        }
      }
      setUpload({ ...u })
    }, 160)
  }

  return { upload, start }
}
