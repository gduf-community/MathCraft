/** 新建题库弹窗：填写名称（编号自动生成）、上传文档（暂存，随创建一并入库）；不含权限与成员设置 */
import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { FileUp, FolderPlus, Trash2, X } from 'lucide-react'
import * as bankMock from '../../../api/mock/bankMock'
import type { BankDoc } from '../../../api/mock/bankMock'
import { useApp } from '../../../store/AppContext'
import { FormatBadge, SectionTitle } from './shared'

const FORMATS = ['PDF', 'DOCX', 'XLSX', 'MD']
const fmtOf = (name: string) => {
  const ext = name.split('.').pop()?.toUpperCase() ?? 'PDF'
  return FORMATS.includes(ext) ? ext : 'PDF'
}

interface UploadState {
  name: string
  phase: 'upload' | 'vector' | 'done'
  pct: number
}

export default function BankCreateModal({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const { showToast } = useApp()
  const year = new Date().getFullYear()
  const [name, setName] = useState('')
  const [docs, setDocs] = useState<BankDoc[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [upload, setUpload] = useState<UploadState | null>(null)
  const uploadState = useRef<UploadState | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const start = (name: string, size: string) => {
    if (uploadState.current) return
    const format = fmtOf(name)
    uploadState.current = { name, phase: 'upload', pct: 0 }
    setUpload({ ...uploadState.current })
    const iv = window.setInterval(() => {
      const u = uploadState.current
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
          setDocs((prev) => [...prev, { id: `d-${Date.now()}`, name, format, size }])
          window.setTimeout(() => {
            uploadState.current = null
            setUpload(null)
          }, 500)
        }
      }
      setUpload({ ...u })
    }, 160)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) start(file.name, `${(file.size / 1024 / 1024).toFixed(1)} MB`)
  }

  const submit = async () => {
    if (!name.trim()) {
      showToast('请输入题库名称')
      return
    }
    await bankMock.createBank(name.trim(), docs.map((d) => ({ name: d.name, format: d.format, size: d.size })))
    showToast(`题库「${name.trim()}」创建成功`)
    onChanged()
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={onClose}>
      <div
        className="flex max-h-[80vh] w-[520px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 弹窗头部 */}
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
          {/* 基本信息 */}
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

          {/* 文档上传 */}
          <section className="space-y-2.5">
            <SectionTitle icon={FileUp}>上传文档（{docs.length}）</SectionTitle>
            {docs.length === 0 && <p className="text-xs text-ink-3">题库文档为空，可现在上传，也可以创建后再上传</p>}
            <ul className="space-y-1.5">
              {docs.map((d) => (
                <li key={d.id} className="flex items-center gap-2.5 rounded-lg border border-line px-3 py-2">
                  <FormatBadge format={d.format} />
                  <span className="flex-1 truncate text-sm text-ink">{d.name}</span>
                  <span className="text-xs text-ink-3">{d.size}</span>
                  <button
                    type="button"
                    onClick={() => setDocs((prev) => prev.filter((x) => x.id !== d.id))}
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
              <p className="text-xs text-ink-3">支持 PDF / DOCX / XLSX / MD，上传后自动向量化</p>
              <input
                ref={fileInput}
                type="file"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) start(f.name, `${(f.size / 1024 / 1024).toFixed(1)} MB`)
                  e.target.value = ''
                }}
              />
            </div>
            {upload && (
              <div className="rounded-xl border border-primary/30 bg-primary-light/30 p-3">
                <div className="mb-1.5 flex items-center justify-between text-xs">
                  <span className="truncate font-medium text-ink">{upload.name}</span>
                  <span className={upload.phase === 'done' ? 'text-emerald-600' : 'text-primary'}>
                    {upload.phase === 'upload' && `上传中 ${Math.floor(upload.pct)}%`}
                    {upload.phase === 'vector' && `向量化中 ${Math.floor(upload.pct)}%`}
                    {upload.phase === 'done' && '已完成'}
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-white">
                  <div
                    className={`h-full rounded-full transition-all duration-150 ${upload.phase === 'vector' ? 'bg-violet-500' : 'bg-primary'}`}
                    style={{ width: `${upload.pct}%` }}
                  />
                </div>
              </div>
            )}
          </section>
        </div>

        {/* 底部操作 */}
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
            className="rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6]"
          >
            新建
          </button>
        </div>
      </div>
    </div>
  )
}
