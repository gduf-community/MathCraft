/** 新建题库弹窗：创建题库并上传文档，入库在后台异步进行，关闭后用 toast 提示预计等待。 */
import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { FileUp, FolderPlus, Trash2, X } from 'lucide-react'
import * as bankApi from '../../../api/banks'
import { formatFileSize } from '../../../api/backend'
import { assertCurrentSession, getSessionGeneration } from '../../../api/session'
import { useApp } from '../../../store/AppContext'
import { FormatBadge, SectionTitle } from './shared'

const FORMATS = ['PDF', 'DOCX', 'XLSX', 'MD', 'TXT']
const fmtOf = (name: string) => {
  const ext = name.split('.').pop()?.toUpperCase() ?? 'PDF'
  return FORMATS.includes(ext) ? ext : 'PDF'
}

export default function BankCreateModal({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const { role, showToast } = useApp()
  const year = new Date().getFullYear()
  const [name, setName] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const autoFilledRef = useRef('')
  const submitting = useRef(false)

  const addFile = (file: File) => {
    setFiles((prev) => [...prev, file])
    // 便捷填充：题库名为空或仍是上次自动填充值时，用文档名（去后缀）填入
    const base = file.name.replace(/\.[^.]+$/, '').trim()
    if (base && (!name.trim() || name.trim() === autoFilledRef.current)) {
      setName(base)
      autoFilledRef.current = base
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) addFile(file)
  }

  const submit = async () => {
    if (role !== 'teacher') {
      showToast('仅教师可以创建题库')
      return
    }
    if (submitting.current) return
    const trimmed = name.trim()
    if (!trimmed) {
      showToast('请输入题库名称')
      return
    }
    const queue = files.slice()
    const started = getSessionGeneration()
    submitting.current = true
    // 点击创建立即关窗：上传与入库都在后台进行，进度通过 toast 与文档行状态呈现
    onClose()
    if (queue.length === 0) {
      try {
        await bankApi.createBank(trimmed)
        assertCurrentSession(started)
        onChanged()
        showToast(`题库「${trimmed}」创建成功`)
      } catch (err) {
        if (started !== getSessionGeneration()) return
        showToast(err instanceof Error ? err.message : '创建题库失败')
      }
      return
    }
    let bankId = ''
    for (let i = 0; i < queue.length; i += 1) {
      const file = queue[i]
      try {
        assertCurrentSession(started)
        showToast(`「${file.name}」正在上传中…`)
        if (i === 0) {
          const r = await bankApi.createBankWithDoc(trimmed, file)
          assertCurrentSession(started)
          bankId = r.bank.id
          showToast(`「${r.documentName}」正在上传中，预计等待 ${r.etaMinutes} 分钟`)
        } else {
          const r = await bankApi.uploadDoc(bankId, file)
          assertCurrentSession(started)
          showToast(`「${file.name}」正在上传中，预计等待 ${r.etaMinutes} 分钟`)
        }
        onChanged()
      } catch (err) {
        if (started !== getSessionGeneration()) return
        showToast(err instanceof Error ? err.message : '上传失败')
        if (!bankId) return
      }
    }
  }

  if (role !== 'teacher') return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={onClose}>
      <div
        className="flex max-h-[80vh] w-[520px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <FolderPlus size={18} className="text-primary" />
            <h3 className="text-base font-bold text-ink">新建题库</h3>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink">
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
            {files.length === 0 && <p className="text-xs text-ink-3">题库文档为空，可现在上传，也可以创建后再上传</p>}
            <ul className="space-y-1.5">
              {files.map((d, idx) => (
                <li key={`${d.name}-${idx}`} className="flex items-center gap-2.5 rounded-lg border border-line px-3 py-2">
                  <FormatBadge format={fmtOf(d.name)} />
                  <span className="flex-1 truncate text-sm text-ink">{d.name}</span>
                  <span className="text-xs text-ink-3">{formatFileSize(d.size)}</span>
                  <button
                    type="button"
                    onClick={() => setFiles((prev) => prev.filter((_x, i) => i !== idx))}
                    className="rounded p-1 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-500"
                    title="移除文档"
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
            <div
              onDragOver={(e) => {
                e.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => fileInput.current?.click()}
              className={`flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed px-4 py-5 text-center transition-colors ${
                dragOver ? 'border-primary bg-primary-light/40' : 'border-line hover:border-primary/50 hover:bg-page'
              }`}
            >
              <FileUp size={20} className="text-primary" />
              <p className="text-sm text-ink-2">点击选择或拖拽文件到此处上传</p>
              <p className="text-xs text-ink-3">支持 PDF / DOCX / XLSX / MD / TXT，创建后自动解析入库</p>
              <input
                ref={fileInput}
                type="file"
                accept=".pdf,.docx,.xlsx,.md,.markdown,.txt"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) addFile(f)
                  e.target.value = ''
                }}
              />
            </div>
          </section>
        </div>

        <div className="flex justify-end gap-2.5 border-t border-line px-5 py-3.5">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:bg-page"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6] disabled:opacity-60"
          >
            创建
          </button>
        </div>
      </div>
    </div>
  )
}
