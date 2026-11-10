/** 串行提交批量文档；受理后由服务端异步入库，列表继续展示处理进度。 */
import { useRef, useState } from 'react'
import * as bankApi from '../../../api/banks'
import { getSessionGeneration } from '../../../api/session'
import type { ToastVariant } from '../../../store/ToastContext'
import { validateUploadFiles } from './uploadFiles'

export function useDocUpload(
  bankId: string,
  onQueued: () => void,
  notify: (message: string, variant?: ToastVariant) => void,
) {
  const lock = useRef(false)
  const accepted = useRef<File[]>([])
  const [busy, setBusy] = useState(false)

  const start = async (incoming: Iterable<File>) => {
    if (lock.current) {
      notify('文档正在批量上传，请等待本批完成后再加入文件', 'error')
      return
    }
    const { files, errors } = validateUploadFiles(incoming, accepted.current)
    if (errors.length) notify(errors.join('\n'), 'error')
    if (!files.length) return
    const started = getSessionGeneration()
    lock.current = true
    setBusy(true)
    const failures: string[] = []
    try {
      for (const file of files) {
        if (started !== getSessionGeneration()) return
        notify(`正在上传「${file.name}」…`, 'info')
        try {
          await bankApi.uploadDoc(bankId, file)
        } catch (error) {
          if (started !== getSessionGeneration()) return
          const message = `「${file.name}」上传失败：${error instanceof Error ? error.message : '请重试'}`
          failures.push(message)
          notify(message, 'error')
          continue
        }
        if (started !== getSessionGeneration()) return
        accepted.current.push(file)
        onQueued()
      }
      if (failures.length || errors.length) {
        notify([...errors, ...failures, `本批已受理 ${files.length - failures.length} 个文档；请重新选择未提交文件重试`].join('\n'), 'error')
      } else {
        notify(`${files.length} 个文档已全部受理，正在后台解析入库`, 'success')
      }
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  return { start, busy }
}
