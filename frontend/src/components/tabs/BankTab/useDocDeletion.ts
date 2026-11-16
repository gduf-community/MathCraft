/** 删除失败后重新读取待清资料，保留同一 DELETE 的重试入口。 */
import { useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import * as bankApi from '../../../api/banks'
import type { BankDoc } from '../../../api/banks'
import { assertCurrentSession, getSessionGeneration } from '../../../api/session'
import { useToast } from '../../../store/ToastContext'

export function useDocDeletion(
  bankId: string,
  setDocs: Dispatch<SetStateAction<BankDoc[]>>,
  onChanged: (deletedDocumentId?: string) => void,
) {
  const { showToast } = useToast()
  const locks = useRef(new Set<string>())
  const [pendingIds, setPendingIds] = useState(new Set<string>())

  const remove = async (doc: BankDoc) => {
    if (locks.current.has(doc.id)) return
    locks.current.add(doc.id)
    setPendingIds(new Set(locks.current))
    const started = getSessionGeneration()
    try {
      try {
        await bankApi.removeDoc(bankId, doc.id)
      } catch (err) {
        assertCurrentSession(started)
        showToast(err instanceof Error ? err.message : '删除文档失败，请重试', 'error')
        try {
          const fresh = await bankApi.getBankDetail(bankId)
          assertCurrentSession(started)
          setDocs(fresh.docs)
          if (fresh.docs.some((item) => item.id === doc.id && item.status === 'deleting')) {
            onChanged(doc.id)
          }
        } catch (refreshError) {
          assertCurrentSession(started)
          showToast(`删除未完成，读取最新状态失败：${refreshError instanceof Error ? refreshError.message : '请重新打开题库核对'}`, 'error')
        }
        return
      }
      assertCurrentSession(started)
      setDocs((prev) => prev.filter((item) => item.id !== doc.id))
      showToast(`文档「${doc.name}」已删除`, 'success')
      onChanged(doc.id)
    } catch (err) {
      if (started === getSessionGeneration()) {
        showToast(err instanceof Error ? err.message : '更新文档状态失败', 'error')
      }
    } finally {
      locks.current.delete(doc.id)
      setPendingIds(new Set(locks.current))
    }
  }

  return { remove, pendingIds }
}
