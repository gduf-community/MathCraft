/** 题库查看弹窗：浏览信息与成员；上传需管理员，删除文档需超级管理员，文档可下载 */
import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import {
  Ban,
  Crown,
  Download,
  FileUp,
  FolderOpen,
  Lock,
  ShieldCheck,
  Users,
  X,
} from 'lucide-react'
import * as bankMock from '../../../api/mock/bankMock'
import type { ManagedBank } from '../../../api/mock/bankMock'
import { useApp } from '../../../store/AppContext'
import { Avatar, FormatBadge, SectionTitle } from './shared'
import { useDocUpload } from './useDocUpload'

export default function BankViewModal({
  bank,
  onClose,
  onChanged,
}: {
  bank: ManagedBank
  onClose: () => void
  onChanged: () => void
}) {
  const { showToast } = useApp()
  const [docs, setDocs] = useState(bank.docs)
  const [dragOver, setDragOver] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const isAdmin = bankMock.isMyAdmin(bank)
  const isSuper = bankMock.isMySuperAdmin(bank)
  const canUpload = isAdmin
  const { upload, start } = useDocUpload(bank.id, (doc) => setDocs((prev) => [...prev, doc]), showToast)

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    if (!canUpload) return
    const file = e.dataTransfer.files?.[0]
    if (file) start(file.name, `${(file.size / 1024 / 1024).toFixed(1)} MB`)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={onClose}>
      <div
        className="flex max-h-[88vh] w-[580px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 弹窗头部 */}
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <FolderOpen size={18} className="text-primary" />
            <h3 className="text-base font-bold text-ink">查看题库 · {bank.name}</h3>
            {isAdmin ? (
              <span className="inline-flex items-center gap-0.5 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600">
                <Crown size={10} /> {isSuper ? '超级管理员' : '普通管理员'}
              </span>
            ) : (
              <span className="rounded bg-page px-1.5 py-0.5 text-[10px] text-ink-3">普通成员</span>
            )}
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
          {/* 基本信息（只读） */}
          <section className="grid grid-cols-2 gap-2.5">
            <div className="rounded-xl border border-line p-3">
              <p className="text-xs text-ink-3">题库名称</p>
              <p className="mt-0.5 text-sm font-medium text-ink">{bank.name}</p>
            </div>
            <div className="rounded-xl border border-line p-3">
              <p className="text-xs text-ink-3">题库编号</p>
              <p className="mt-0.5 text-sm font-medium text-ink">{bank.code}</p>
            </div>
            <div className="rounded-xl border border-line p-3">
              <p className="text-xs text-ink-3">题库人数</p>
              <p className="mt-0.5 text-sm font-medium text-ink">
                {bank.memberCount} / {bank.capacity}
              </p>
            </div>
            <div className="rounded-xl border border-line p-3">
              <p className="text-xs text-ink-3">创建者</p>
              <p className="mt-0.5 text-sm font-medium text-ink">{bank.creator}</p>
            </div>
          </section>

          {/* 管理员权限说明（只读） */}
          <section className="space-y-2.5">
            <SectionTitle icon={ShieldCheck}>管理员权限说明</SectionTitle>
            <div className="space-y-2 rounded-xl border border-line p-3">
              <div className={`flex items-center justify-between gap-3 rounded-lg px-2.5 py-2 ${bank.adminLevel === 'normal' ? 'bg-primary-light/40' : ''}`}>
                <span className={`text-sm ${bank.adminLevel === 'normal' ? 'font-semibold text-primary' : 'text-ink'}`}>普通管理员</span>
                <span className="text-xs text-ink-3">可上传和下载文档</span>
              </div>
              <div className={`flex items-center justify-between gap-3 rounded-lg px-2.5 py-2 ${bank.adminLevel === 'super' ? 'bg-primary-light/40' : ''}`}>
                <span className={`text-sm ${bank.adminLevel === 'super' ? 'font-semibold text-primary' : 'text-ink'}`}>超级管理员</span>
                <span className="text-xs text-ink-3">可编辑文档，包括删除、上传、下载和查看</span>
              </div>
            </div>
          </section>

          {/* 成员列表 */}
          <section className="space-y-2.5">
            <SectionTitle icon={Users}>题库成员（{bank.members.length} 人）</SectionTitle>
            <ul className="divide-y divide-line/60 rounded-xl border border-line">
              {bank.members.map((m) => {
                const isCreator = m.name === bank.creator
                return (
                  <li key={m.id} className="flex items-center gap-2.5 px-3 py-2.5">
                    <Avatar name={m.name} size="sm" />
                    <span className="text-sm text-ink">{m.name}</span>
                    {isCreator && (
                      <span className="inline-flex items-center gap-0.5 rounded bg-primary-light px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                        <Crown size={10} /> 创建者
                      </span>
                    )}
                    {!isCreator && m.isAdmin && (
                      <span className="inline-flex items-center gap-0.5 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600">
                        {bank.adminLevel === 'super' ? '超级管理员' : '普通管理员'}
                      </span>
                    )}
                    {m.name === bankMock.CURRENT_USER && (
                      <span className="rounded bg-page px-1.5 py-0.5 text-[10px] text-ink-3">我</span>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>

          {/* 文档列表 */}
          <section className="space-y-2.5">
            <SectionTitle icon={FileUp}>已上传文档（{docs.length}）</SectionTitle>
            {docs.length === 0 && <p className="text-xs text-ink-3">暂无文档</p>}
            <ul className="space-y-1.5">
              {docs.map((d) => (
                <li key={d.id} className="flex items-center gap-2.5 rounded-lg border border-line px-3 py-2">
                  <FormatBadge format={d.format} />
                  <span className="flex-1 truncate text-sm text-ink">{d.name}</span>
                  <span className="text-xs text-ink-3">{d.size}</span>
                  <button
                    type="button"
                    title="下载文档"
                    onClick={() => showToast(`已开始下载「${d.name}」（演示）`)}
                    className="rounded p-1 text-ink-3 transition-colors hover:bg-primary-light hover:text-primary"
                  >
                    <Download size={14} />
                  </button>
                  {isSuper && (
                    <button
                      type="button"
                      title="删除文档（超级管理员）"
                      onClick={async () => {
                        await bankMock.removeDoc(bank.id, d.id)
                        setDocs((prev) => prev.filter((x) => x.id !== d.id))
                        onChanged()
                      }}
                      className="rounded p-1 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-500"
                    >
                      <Ban size={14} />
                    </button>
                  )}
                </li>
              ))}
            </ul>

            {/* 上传区域：管理员可上传 */}
            {canUpload ? (
              <>
                <div
                  onDragOver={(e) => {
                    e.preventDefault()
                    setDragOver(true)
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={onDrop}
                  onClick={() => fileInput.current?.click()}
                  className={`flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed px-4 py-4 text-center transition-colors ${
                    dragOver ? 'border-primary bg-primary-light/40' : 'border-line hover:border-primary/50 hover:bg-page'
                  }`}
                >
                  <FileUp size={18} className="text-primary" />
                  <p className="text-sm text-ink-2">点击选择或拖拽文件到此处上传</p>
                  <p className="text-xs text-ink-3">上传后自动向量化</p>
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
              </>
            ) : (
              <div className="flex items-center gap-2.5 rounded-xl border border-dashed border-line bg-page px-4 py-3.5 text-ink-3">
                <Lock size={15} className="shrink-0" />
                <p className="text-xs leading-5">上传文档需要管理员权限，当前你在该题库为普通成员</p>
              </div>
            )}
          </section>
        </div>

        {/* 底部 */}
        <div className="flex justify-end border-t border-line px-5 py-3.5">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:bg-page"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}
