/** 题库信息编辑弹窗：基本信息、创建者管理成员、文档预览与入库进度 */
import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import {
  Download,
  Eye,
  FileUp,
  FolderCog,
  RotateCcw,
  Settings2,
  Trash2,
  UserX,
  Users,
  X,
} from 'lucide-react'
import * as bankApi from '../../../api/banks'
import type { ManagedBank } from '../../../api/banks'
import { assertCurrentSession, getSessionGeneration } from '../../../api/session'
import { useApp } from '../../../store/AppContext'
import { Avatar, FormatBadge, SectionTitle } from './shared'
import DocPreviewModal from './DocPreviewModal'
import { useDocUpload } from './useDocUpload'

export default function BankEditModal({
  bank,
  onClose,
  onChanged,
}: {
  bank: ManagedBank
  onClose: () => void
  onChanged: () => void
}) {
  const { showToast } = useApp()
  const [name, setName] = useState(bank.name)
  const [memberAccount, setMemberAccount] = useState('')
  const [memberRole, setMemberRole] = useState<'editor' | 'readonly'>('readonly')
  const [docs, setDocs] = useState(bank.docs)
  const [members, setMembers] = useState(bank.members)
  const [preview, setPreview] = useState<{ id: string; name: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const session = useRef(getSessionGeneration())
  const { start } = useDocUpload(bank.id, () => {
    void bankApi.getBankDetail(bank.id).then((fresh) => setDocs(fresh.docs))
      .catch((err) => showToast(err instanceof Error ? err.message : '刷新文档失败'))
  }, showToast)

  const iconBtn = 'flex h-7 w-7 items-center justify-center rounded-md transition-colors'

  // 有文档正在上传/解析/向量化时，每 3 秒轮询一次处理阶段
  const processing = docs.some((d) => d.status && !['ready', 'failed'].includes(d.status))
  useEffect(() => {
    if (!processing) return
    const timer = window.setInterval(() => {
      if (session.current !== getSessionGeneration()) return
      void bankApi
        .getBankDetail(bank.id)
        .then((fresh) => setDocs(fresh.docs))
        .catch((err) => showToast(err instanceof Error ? err.message : '刷新文档失败'))
    }, 3000)
    return () => window.clearInterval(timer)
  }, [processing, bank.id, showToast])

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    if (!bank.canUpload) return
    const file = e.dataTransfer.files?.[0]
    if (file) start(file)
  }

  const save = async () => {
    if (!bank.canEdit || saving) return
    if (!name.trim()) {
      showToast('题库名称不能为空')
      return
    }
    setSaving(true)
    try {
      await bankApi.updateBank(bank.id, { name: name.trim() })
      showToast('题库信息已保存')
      onChanged()
      onClose()
    } catch (err) {
      showToast(err instanceof Error ? err.message : '保存题库失败')
    } finally {
      setSaving(false)
    }
  }

  if (!bank.canEdit) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={onClose}>
      <div
        className="flex max-h-[88vh] w-[620px] max-w-full flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 弹窗头部 */}
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <FolderCog size={18} className="text-primary" />
            <h3 className="text-base font-bold text-ink">题库信息 · {bank.name}</h3>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
          {/* 基本信息 */}
          <section className="space-y-2.5">
            <SectionTitle icon={Settings2}>基本信息</SectionTitle>
            <label className="block">
              <span className="mb-1 block text-xs text-ink-3">题库名称</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="block w-full rounded-lg border border-line px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-ink-3">题库编号（只读）</span>
              <input
                type="text"
                value={bank.code}
                readOnly
                className="block w-full cursor-not-allowed rounded-lg border border-line bg-page px-3 py-2 text-sm text-ink-2"
              />
            </label>
          </section>

          {/* 成员权限 */}
          {bank.canManageMembers && <section className="space-y-2.5">
            <SectionTitle icon={Users}>成员权限</SectionTitle>
            <p className="text-xs text-ink-3">创建者可按登录账号添加成员。可编辑成员能维护共享资料，只读成员只能查看、下载、检索和出题。</p>
            <div className="flex gap-2">
              <label className="sr-only" htmlFor="member-account">成员登录账号</label>
              <input
                id="member-account"
                value={memberAccount}
                onChange={(event) => setMemberAccount(event.target.value)}
                placeholder="登录账号"
                className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2 text-sm"
              />
              <label className="sr-only" htmlFor="member-role">成员权限</label>
              <select
                id="member-role"
                value={memberRole}
                onChange={(event) => {
                  if (event.target.value === 'editor' || event.target.value === 'readonly') {
                    setMemberRole(event.target.value)
                  }
                }}
                className="rounded-lg border border-line px-3 py-2 text-sm"
              >
                <option value="readonly">只读</option>
                <option value="editor">可编辑</option>
              </select>
              <button
                type="button"
                onClick={async () => {
                  try {
                    const member = await bankApi.addMember(bank.id, memberAccount.trim(), memberRole)
                    setMembers((prev) => [...prev, member])
                    setMemberAccount('')
                    showToast('成员已添加')
                    onChanged()
                  } catch (err) {
                    showToast(err instanceof Error ? err.message : '添加成员失败')
                  }
                }}
                disabled={!memberAccount.trim()}
                className="rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
              >
                添加
              </button>
            </div>
          </section>}

          {/* 成员列表 */}
          <section className="space-y-2.5">
            <SectionTitle icon={Users}>题库成员（{members.length} 人）</SectionTitle>
            <ul className="divide-y divide-line/60 rounded-xl border border-line">
              {members.map((member) => (
                <li key={member.id} className="flex items-center justify-between gap-2 px-3 py-2.5">
                  <div className="flex items-center gap-2.5">
                    <Avatar name={member.name} size="sm" />
                    <span className="text-sm text-ink">{member.name}</span>
                    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${member.isCreator ? 'bg-primary-light text-primary' : member.role === 'editor' ? 'bg-amber-50 text-amber-600' : 'bg-page text-ink-3'}`}>
                      {member.isCreator ? '创建者' : member.role === 'editor' ? '可编辑' : '只读'}
                    </span>
                    {member.isMe && <span className="rounded bg-page px-1.5 py-0.5 text-[10px] text-ink-3">我</span>}
                  </div>
                  {bank.canManageMembers && !member.isMe && !member.isCreator && (
                    <div className="flex items-center gap-2">
                      <select
                        aria-label={`${member.name}的权限`}
                        value={member.role}
                        onChange={async (event) => {
                          const role = event.target.value
                          if (role !== 'editor' && role !== 'readonly') return
                          try {
                            await bankApi.setMemberRole(bank.id, member.id, role)
                            setMembers((prev) => prev.map((item) => item.id === member.id ? { ...item, role } : item))
                            showToast('成员权限已更新')
                            onChanged()
                          } catch (err) {
                            showToast(err instanceof Error ? err.message : '更新成员权限失败')
                          }
                        }}
                        className="rounded border border-line px-2 py-1 text-xs"
                      >
                        <option value="readonly">只读</option>
                        <option value="editor">可编辑</option>
                      </select>
                      <button
                        type="button"
                        title="移出题库"
                        onClick={async () => {
                          try {
                            await bankApi.removeMember(bank.id, member.id)
                            setMembers((prev) => prev.filter((item) => item.id !== member.id))
                            showToast(`已将 ${member.name} 移出题库`)
                            onChanged()
                          } catch (err) {
                            showToast(err instanceof Error ? err.message : '移出成员失败')
                          }
                        }}
                        className={`${iconBtn} text-red-500 hover:bg-red-50`}
                      >
                        <UserX size={14} />
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>

          {/* 文档列表 */}
          <section className="space-y-2.5">
            <SectionTitle icon={FileUp}>已上传文档（{docs.length}）</SectionTitle>
            {docs.length === 0 && <p className="text-xs text-ink-3">暂无文档，可在下方上传</p>}
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
                      {failed && (
                        <button
                          type="button"
                          title="重新解析"
                          onClick={() => {
                            void bankApi
                              .reprocessDoc(bank.id, d.id)
                              .then(() => {
                                assertCurrentSession(session.current)
                                showToast(`「${d.name}」已重新排队解析`)
                                return bankApi.getBankDetail(bank.id).then((fresh) => setDocs(fresh.docs))
                              })
                              .catch((err) => showToast(err instanceof Error ? err.message : '操作失败'))
                          }}
                          className="rounded p-1 text-ink-3 transition-colors hover:bg-primary-light hover:text-primary"
                        >
                          <RotateCcw size={14} />
                        </button>
                      )}
                      <button
                        type="button"
                        title="查看文档"
                        onClick={() => setPreview({ id: d.id, name: d.name })}
                        className="rounded p-1 text-ink-3 transition-colors hover:bg-primary-light hover:text-primary"
                      >
                        <Eye size={14} />
                      </button>
                      <button
                        type="button"
                        title="下载文档"
                        onClick={() => void bankApi.downloadDoc(bank.id, d.id, d.name).catch((err) => showToast(err instanceof Error ? err.message : '下载失败'))}
                        className="rounded p-1 text-ink-3 transition-colors hover:bg-primary-light hover:text-primary"
                      >
                        <Download size={14} />
                      </button>
                      <button
                        type="button"
                        title="删除文档"
                        onClick={async () => {
                          try {
                            await bankApi.removeDoc(bank.id, d.id)
                            setDocs((prev) => prev.filter((x) => x.id !== d.id))
                            onChanged()
                          } catch (err) {
                            showToast(err instanceof Error ? err.message : '删除文档失败')
                          }
                        }}
                        className="rounded p-1 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-500"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>

            {/* 上传区域 */}
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
              <p className="text-xs text-ink-3">支持 PDF / DOCX / XLSX / MD / TXT，上传后自动向量化</p>
              <input
                ref={fileInput}
                type="file"
                accept=".pdf,.docx,.xlsx,.md,.markdown,.txt"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) start(f)
                  e.target.value = ''
                }}
              />
            </div>
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
            onClick={() => void save()}
            disabled={saving}
            className="rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6]"
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>

      {preview && (
        <DocPreviewModal
          key={preview.id}
          bankId={bank.id}
          docId={preview.id}
          docName={preview.name}
          onClose={() => setPreview(null)}
        />
      )}

    </div>
  )
}
