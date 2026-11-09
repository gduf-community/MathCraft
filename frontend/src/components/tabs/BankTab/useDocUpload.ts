/** 文档上传：提交后立即返回，入库异步进行；弹窗轮询展示文档行状态，完成有站内通知。 */
import { useRef } from 'react'
import * as bankApi from '../../../api/banks'
import { getSessionGeneration } from '../../../api/session'

export function useDocUpload(bankId: string, onQueued: () => void, notify: (msg: string) => void) {
  const busy = useRef(false)

  const start = (file: File) => {
    if (busy.current) return
    const started = getSessionGeneration()
    busy.current = true
    notify(`正在上传「${file.name}」…`)
    void bankApi
      .uploadDoc(bankId, file)
      .then((r) => {
        if (started !== getSessionGeneration()) return
        onQueued()
        notify(`「${file.name}」正在上传中，预计等待 ${r.etaMinutes} 分钟`)
      })
      .catch((err) => {
        if (started === getSessionGeneration()) notify(err instanceof Error ? err.message : '上传失败')
      })
      .finally(() => {
        busy.current = false
      })
  }

  return { start }
}
