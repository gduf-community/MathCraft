/** 新建题库弹窗：串行受理上传，保留未提交草稿与已创建题库，入库由后台继续。 */
import { useRef, useState } from 'react'
import { FileUp, FolderPlus, Trash2, X } from 'lucide-react'
import * as bankApi from '../../../api/banks'
import { createBank, createBankWithDocument, formatFileSize } from '../../../api/backend'
import { assertCurrentSession, getSessionGeneration } from '../../../api/session'
import { useApp } from '../../../store/AppContext'
import { DocumentDropZone, FormatBadge, SectionTitle } from './shared'
import { documentFormat, uploadFileKey, validateUploadFiles } from './uploadFiles'

export default function BankCreateModal({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const { role, showToast } = useApp()
  const year = new Date().getFullYear()
  const [name, setName] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [bankId, setBankId] = useState('')
  const [error, setError] = useState('')
  const accepted = useRef<File[]>([])
  const autoFilledRef = useRef('')
  const submitting = useRef(false)

  const addFiles = (incoming: File[]) => {
    if (submitting.current) {
      showToast('文档正在批量上传，请等待本批完成后再加入文件', 'error')
      return
    }
    const result = validateUploadFiles(incoming, [...files, ...accepted.current])
    if (result.errors.length) showToast(result.errors.join('\n'), 'error')
    if (!result.files.length) return
    setFiles((prev) => [...prev, ...result.files])
    const file = result.files[0]
    // 便捷填充：题库名为空或仍是上次自动填充值时，用文档名（去后缀）填入
    const base = file.name.replace(/\.[^.]+$/, '').trim()
    if (!bankId && base && (!name.trim() || name.trim() === autoFilledRef.current)) {
      setName(base)
      autoFilledRef.current = base
    }
  }

  const close = () => {
    if (submitting.current) {
      showToast('文档正在批量上传，请等待本批完成后再关闭', 'error')
      return
    }
    onClose()
  }

  const submit = async () => {
    if (role !== 'teacher') {
      showToast('仅教师可以创建题库', 'error')
      return
    }
    if (submitting.current) return
    const trimmed = name.trim()
    if (!trimmed) {
      setError('请输入题库名称')
      showToast('请输入题库名称', 'error')
      return
    }
    const queue = files.slice()
    const started = getSessionGeneration()
    submitting.current = true
    setBusy(true)
    setError('')
    let currentBankId = bankId
    const failures: string[] = []
    try {
      if (queue.length === 0 && !currentBankId) {
        const created = await createBank(trimmed)
        assertCurrentSession(started)
        currentBankId = created.id
        setBankId(created.id)
        onChanged()
      }
      for (const file of queue) {
        assertCurrentSession(started)
        showToast(`「${file.name}」正在上传中…`, 'info')
        try {
          if (!currentBankId) {
            // 直接记录写请求的受理结果，后续列表刷新失败不能让重试重复建库。
            const result = await createBankWithDocument(trimmed, file)
            assertCurrentSession(started)
            currentBankId = result.bank.id
            setBankId(currentBankId)
          } else {
            await bankApi.uploadDoc(currentBankId, file)
          }
          assertCurrentSession(started)
          accepted.current.push(file)
          setFiles((prev) => prev.filter((item) => uploadFileKey(item) !== uploadFileKey(file)))
          onChanged()
        } catch (err) {
          if (started !== getSessionGeneration()) return
          const message = `「${file.name}」上传失败：${err instanceof Error ? err.message : '请重试'}`
          failures.push(message)
          setError(message)
          showToast(message, 'error')
          if (!currentBankId) break
        }
      }
      if (failures.length) {
        const message = failures.join('\n')
        setError(message)
        showToast(message, 'error')
        return
      }
      assertCurrentSession(started)
      showToast(queue.length ? `题库「${trimmed}」的文档已全部受理，正在后台解析入库` : `题库「${trimmed}」创建成功`, 'success')
      onClose()
    } catch (err) {
      if (started !== getSessionGeneration()) return
      const message = err instanceof Error ? err.message : '创建题库失败'
      setError(message)
      showToast(message, 'error')
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  if (role !== 'teacher') return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={close}
      onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); close() } }}>
      <div
        role="dialog" aria-modal="true" aria-label="新建题库" aria-busy={busy}
        className="flex max-h-[80vh] w-[520px] max-w-full flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <FolderPlus size={18} className="text-primary" />
            <h3 className="text-base font-bold text-ink">新建题库</h3>
          </div>
          <button type="button" onClick={close} disabled={busy} aria-label="关闭新建题库" className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink disabled:opacity-50">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
          <section className="space-y-2.5">
            <SectionTitle icon={FolderPlus}>基本信息</SectionTitle>
            <label className="block">
              <span className="mb-1 block text-xs text-ink-3">题库名称</span>
              <input
                type="text"
                value={name}
                disabled={busy || !!bankId}
                maxLength={40}
                onChange={(e) => setName(e.target.value)}
                placeholder="如：2026级高等数学"
                className="block w-full rounded-lg border border-line px-3 py-2 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-ink-3">题库编号（创建后自动生成）</span>
              <input
                type="text"
                value={`TK${year}••••`}
                readOnly
                className="block w-full cursor-not-allowed rounded-lg border border-line bg-page px-3 py-2 text-sm text-ink-2"
              />
            </label>
          </section>

          <section className="space-y-2.5">
            <SectionTitle icon={FileUp}>上传文档（{files.length}）</SectionTitle>
            {error && <p role="alert" className="whitespace-pre-wrap text-sm text-red-700">{error}</p>}
            {bankId && <p role="status" className="text-xs text-ink-2">题库已创建，重试仅提交下方未受理文件，不会重复建库。</p>}
            {files.length === 0 && <p className="text-xs text-ink-3">题库文档为空，可现在上传，也可以创建后再上传</p>}
            <ul className="space-y-1.5">
              {files.map((d) => (
                <li key={uploadFileKey(d)} className="flex items-center gap-2.5 rounded-lg border border-line px-3 py-2">
                  <FormatBadge format={documentFormat(d.name) ?? ''} />
                  <span className="flex-1 truncate text-sm text-ink">{d.name}</span>
                  <span className="text-xs text-ink-3">{formatFileSize(d.size)}</span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setFiles((prev) => prev.filter((file) => uploadFileKey(file) !== uploadFileKey(d)))}
                    aria-label={`移除${d.name}`}
                    className="rounded p-1 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-500"
                    title="移除文档"
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
            <DocumentDropZone onFiles={addFiles} busy={busy} />
          </section>
        </div>

        <div className="flex justify-end gap-2.5 border-t border-line px-5 py-3.5">
          <button
            type="button"
            onClick={close}
            disabled={busy}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:bg-page"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6] disabled:opacity-60"
          >
            {busy ? '上传受理中…' : bankId ? (files.length ? '重试未提交文件' : '完成') : '创建'}
          </button>
        </div>
      </div>
    </div>
  )
}
