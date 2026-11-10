/** 题库查看弹窗：浏览信息、成员权限和文档操作。 */
import { useEffect, useRef, useState } from 'react'
import {
  Ban,
  Download,
  Eye,
  FileUp,
  FolderOpen,
  Lock,
  ShieldCheck,
  Users,
  X,
} from 'lucide-react'
import * as bankApi from '../../../api/banks'
import type { BankDoc, ManagedBank } from '../../../api/banks'
import { openPdfDocument } from '../../../api/documentPreview'
import { assertCurrentSession, getSessionGeneration } from '../../../api/session'
import { useApp } from '../../../store/AppContext'
import { Avatar, DocumentDropZone, DocumentFailure, FormatBadge, SectionTitle } from './shared'
import { useDocUpload } from './useDocUpload'
import DocPreviewModal from './DocPreviewModal'

export default function BankViewModal({
  bank,
  onClose,
  onChanged,
}: {
  bank: ManagedBank
  onClose: () => void
  onChanged: (deletedDocumentId?: string) => void
}) {
  const { showToast } = useApp()
  const [docs, setDocs] = useState(bank.docs)
  const [preview, setPreview] = useState<BankDoc | null>(null)
  const session = useRef(getSessionGeneration())
  const roleLabel = bank.myRole === 'creator' ? '创建者' : bank.myRole === 'editor' ? '可编辑' : '只读'
  const canUpload = bank.canUpload
  const { start, busy: uploading } = useDocUpload(bank.id, () => {
    onChanged()
    void bankApi.getBankDetail(bank.id).then((fresh) => {
      assertCurrentSession(session.current)
      setDocs(fresh.docs)
    })
      .catch((err) => showToast(err instanceof Error ? err.message : '刷新文档失败', 'error'))
  }, showToast)

  const processing = docs.some((doc) => doc.status && !['ready', 'failed'].includes(doc.status))
  useEffect(() => {
    if (!processing) return
    const timer = window.setInterval(() => {
      if (session.current !== getSessionGeneration()) return
      void bankApi.getBankDetail(bank.id).then((fresh) => {
        assertCurrentSession(session.current)
        setDocs(fresh.docs)
      })
        .catch((err) => showToast(err instanceof Error ? err.message : '刷新文档失败', 'error'))
    }, 3000)
    return () => window.clearInterval(timer)
  }, [bank.id, processing, showToast])

  const close = () => {
    if (uploading) {
      showToast('文档正在批量上传，请等待本批完成后再关闭', 'error')
      return
    }
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={close}
      onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); close() } }}>
      <div
        role="dialog" aria-modal="true" aria-label={`查看题库 · ${bank.name}`} aria-busy={uploading}
        className="flex max-h-[88vh] w-[580px] max-w-full flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 弹窗头部 */}
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <FolderOpen size={18} className="text-primary" />
            <h3 className="text-base font-bold text-ink">查看题库 · {bank.name}</h3>
            <span className="rounded bg-page px-1.5 py-0.5 text-[10px] font-semibold text-ink-2">{roleLabel}</span>
          </div>
          <button type="button" onClick={close} disabled={uploading} aria-label="关闭查看题库" className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink disabled:opacity-50">
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

          {/* 成员权限说明（只读） */}
          <section className="space-y-2.5">
            <SectionTitle icon={ShieldCheck}>成员权限说明</SectionTitle>
            <div className="space-y-2 rounded-xl border border-line p-3">
              <div className="flex items-center justify-between gap-3 rounded-lg px-2.5 py-2">
                <span className="text-sm text-ink">创建者</span>
                <span className="text-xs text-ink-3">管理成员、维护资料和删除题库</span>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg px-2.5 py-2">
                <span className="text-sm text-ink">可编辑成员</span>
                <span className="text-xs text-ink-3">查看、下载、检索、出题、上传和删除资料</span>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg px-2.5 py-2">
                <span className="text-sm text-ink">只读成员</span>
                <span className="text-xs text-ink-3">查看、下载、检索和出题</span>
              </div>
            </div>
          </section>

          {/* 成员列表 */}
          <section className="space-y-2.5">
            <SectionTitle icon={Users}>题库成员（{bank.members.length} 人）</SectionTitle>
            <ul className="divide-y divide-line/60 rounded-xl border border-line">
              {bank.members.map((m) => {
                return (
                  <li key={m.id} className="flex items-center gap-2.5 px-3 py-2.5">
                    <Avatar name={m.name} size="sm" />
                    <span className="text-sm text-ink">{m.name}</span>
                    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${m.isCreator ? 'bg-primary-light text-primary' : m.role === 'editor' ? 'bg-amber-50 text-amber-600' : 'bg-page text-ink-3'}`}>
                      {m.isCreator ? '创建者' : m.role === 'editor' ? '可编辑' : '只读'}
                    </span>
                    {m.isMe && (
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
              {docs.map((d) => {
                const busy = d.status && !['ready', 'failed'].includes(d.status)
                const failed = d.status === 'failed'
                return (
                  <li key={d.id} className="rounded-lg border border-line px-3 py-2">
                    <div className="flex items-center gap-2.5">
                    <FormatBadge format={d.format} />
                    <span className="flex-1 truncate text-sm text-ink">{d.name}</span>
                    <span
                      title={failed ? d.stage ?? '' : undefined}
                      className={`mr-3 text-xs ${
                        failed ? 'text-red-500' : busy ? 'text-primary' : 'text-emerald-600'
                      }`}
                    >
                      {failed ? '入库失败' : busy ? `${d.stage ?? '处理中'} ${d.progress ?? 0}%` : '可用'}
                    </span>
                    <button
                      type="button"
                      title="查看文档"
                      onClick={() => {
                        const format = d.format.toUpperCase()
                        if (format === 'PDF') {
                          void openPdfDocument(bank.id, d.id).catch((err) => showToast(err instanceof Error ? err.message : '打开 PDF 失败', 'error'))
                        } else if (['MD', 'MARKDOWN', 'TXT'].includes(format)) {
                          setPreview(d)
                        } else {
                          showToast(`${format} 暂不支持内联预览，请使用下载按钮`, 'info')
                        }
                      }}
                      className="rounded p-1 text-ink-3 transition-colors hover:bg-primary-light hover:text-primary"
                    >
                      <Eye size={14} />
                    </button>
                    <button
                      type="button"
                      title="下载文档"
                      onClick={() => void bankApi.downloadDoc(bank.id, d.id, d.name).catch((err) => showToast(err instanceof Error ? err.message : '下载失败', 'error'))}
                      className="rounded p-1 text-ink-3 transition-colors hover:bg-primary-light hover:text-primary"
                    >
                      <Download size={14} />
                    </button>
                  {bank.canDeleteDoc && (
                    <button
                      type="button"
                      title="删除文档"
                      onClick={async () => {
                        try {
                          await bankApi.removeDoc(bank.id, d.id)
                          assertCurrentSession(session.current)
                          setDocs((prev) => prev.filter((x) => x.id !== d.id))
                          onChanged(d.id)
                        } catch (err) {
                          showToast(err instanceof Error ? err.message : '删除文档失败', 'error')
                        }
                      }}
                      className="rounded p-1 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-500"
                    >
                      <Ban size={14} />
                    </button>
                  )}
                    </div>
                    {['DOCX', 'XLSX'].includes(d.format.toUpperCase()) && <p className="mt-1 text-xs text-ink-3">暂不支持内联预览，请使用下载按钮。</p>}
                    <DocumentFailure doc={d} onRetry={bank.canUpload ? async () => {
                      try {
                        await bankApi.reprocessDoc(bank.id, d.id)
                        assertCurrentSession(session.current)
                        onChanged()
                        showToast(`「${d.name}」已重新排队解析`, 'success')
                        const fresh = await bankApi.getBankDetail(bank.id)
                        assertCurrentSession(session.current)
                        setDocs(fresh.docs)
                      } catch (err) {
                        showToast(err instanceof Error ? err.message : '重新解析失败', 'error')
                      }
                    } : undefined} />
                </li>
                )
              })}
            </ul>

            {/* 上传区域：可编辑成员可上传 */}
            {canUpload ? (
              <>
                <DocumentDropZone busy={uploading} onFiles={(files) => { void start(files) }} />
              </>
            ) : (
              <div className="flex items-center gap-2.5 rounded-xl border border-dashed border-line bg-page px-4 py-3.5 text-ink-3">
                <Lock size={15} className="shrink-0" />
                <p className="text-xs leading-5">当前权限为只读，只能查看、下载、检索和出题</p>
              </div>
            )}
          </section>
        </div>

        {/* 底部 */}
        <div className="flex justify-end border-t border-line px-5 py-3.5">
          <button
            type="button"
            onClick={close}
            disabled={uploading}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:bg-page"
          >
            关闭
          </button>
        </div>
      </div>
      {preview && (
        <DocPreviewModal
          key={preview.id}
          bankId={bank.id}
          docId={preview.id}
          docName={preview.name}
          docFormat={preview.format}
          onClose={() => setPreview(null)}
        />
      )}
    </div>
  )
}
