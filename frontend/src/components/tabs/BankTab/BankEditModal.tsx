/** 题库信息编辑弹窗：基本信息、管理员权限级别、成员管理（设/取消管理员、转让、移出）、文档与上传 */
import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import {
  ArrowLeftRight,
  Crown,
  Download,
  FileUp,
  FolderCog,
  Settings2,
  ShieldCheck,
  Trash2,
  UserMinus,
  UserPlus,
  UserX,
  Users,
  X,
} from 'lucide-react'
import * as bankMock from '../../../api/mock/bankMock'
import type { AdminLevel, ManagedBank } from '../../../api/mock/bankMock'
import { useApp } from '../../../store/AppContext'
import { Avatar, FormatBadge, SectionTitle } from './shared'
import ConfirmDialog from './ConfirmDialog'
import { useDocUpload } from './useDocUpload'

const LEVELS: { key: AdminLevel; title: string; desc: string }[] = [
  { key: 'normal', title: '普通管理员', desc: '可上传和下载文档' },
  { key: 'super', title: '超级管理员', desc: '可编辑文档，包括删除、上传、下载和查看' },
]

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
  const [adminLevel, setAdminLevel] = useState<AdminLevel>(bank.adminLevel)
  const [docs, setDocs] = useState(bank.docs)
  const [members, setMembers] = useState(bank.members)
  const [transferTarget, setTransferTarget] = useState<{ id: string; name: string } | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const { upload, start } = useDocUpload(bank.id, (doc) => setDocs((prev) => [...prev, doc]), showToast)

  const levelLabel = adminLevel === 'super' ? '超级管理员' : '普通管理员'
  const iconBtn = 'flex h-7 w-7 items-center justify-center rounded-md transition-colors'

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) start(file.name, `${(file.size / 1024 / 1024).toFixed(1)} MB`)
  }

  const save = async () => {
    if (!name.trim()) {
      showToast('题库名称不能为空')
      return
    }
    await bankMock.updateBank(bank.id, { name: name.trim(), adminLevel })
    showToast('题库信息已保存')
    onChanged()
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={onClose}>
      <div
        className="flex max-h-[88vh] w-[620px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
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

          {/* 管理员权限级别 */}
          <section className="space-y-2.5">
            <SectionTitle icon={ShieldCheck}>管理员权限级别</SectionTitle>
            <div className="grid grid-cols-2 gap-2.5">
              {LEVELS.map((lv) => (
                <button
                  key={lv.key}
                  type="button"
                  onClick={() => setAdminLevel(lv.key)}
                  className={`rounded-xl border p-3 text-left transition-colors ${
                    adminLevel === lv.key
                      ? 'border-primary bg-primary-light/40 shadow-[0_2px_8px_rgba(30,111,255,0.12)]'
                      : 'border-line hover:border-primary/40 hover:bg-page'
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <ShieldCheck size={14} className={adminLevel === lv.key ? 'text-primary' : 'text-ink-3'} />
                    <span className={`text-sm font-semibold ${adminLevel === lv.key ? 'text-primary' : 'text-ink'}`}>
                      {lv.title}
                    </span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-ink-3">{lv.desc}</p>
                </button>
              ))}
            </div>
            <p className="text-xs text-ink-3">当前级别对本题库全部管理员生效；创建者恒为超级管理员</p>
          </section>

          {/* 成员管理（含设/取消管理员、转让、移出） */}
          <section className="space-y-2.5">
            <SectionTitle icon={Users}>题库成员（{members.length} 人）</SectionTitle>
            <ul className="divide-y divide-line/60 rounded-xl border border-line">
              {members.map((m) => {
                const isCreator = m.name === bank.creator
                const isMe = m.name === bankMock.CURRENT_USER
                return (
                  <li key={m.id} className="flex items-center justify-between gap-2 px-3 py-2.5">
                    <div className="flex items-center gap-2.5">
                      <Avatar name={m.name} size="sm" />
                      <span className="text-sm text-ink">{m.name}</span>
                      {isCreator && (
                        <span className="inline-flex items-center gap-0.5 rounded bg-primary-light px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                          <Crown size={10} /> 创建者
                        </span>
                      )}
                      {!isCreator && m.isAdmin && (
                        <span className="inline-flex items-center gap-0.5 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600">
                          {levelLabel}
                        </span>
                      )}
                      {isMe && <span className="rounded bg-page px-1.5 py-0.5 text-[10px] text-ink-3">我</span>}
                    </div>
                    {!isMe && !isCreator && (
                      <div className="flex items-center gap-1">
                        {m.isAdmin ? (
                          <button
                            type="button"
                            title="取消管理员"
                            onClick={async () => {
                              try {
                                await bankMock.unsetAdmin(bank.id, m.id)
                                setMembers((prev) => prev.map((x) => (x.id === m.id ? { ...x, isAdmin: false } : x)))
                                showToast(`已取消 ${m.name} 的管理员权限`)
                              } catch (err) {
                                showToast(err instanceof Error ? err.message : '操作失败')
                              }
                            }}
                            className={`${iconBtn} text-amber-600 hover:bg-amber-50`}
                          >
                            <UserMinus size={14} />
                          </button>
                        ) : (
                          <button
                            type="button"
                            title={`设为${levelLabel}`}
                            onClick={async () => {
                              await bankMock.setAdmin(bank.id, m.id)
                              setMembers((prev) => prev.map((x) => (x.id === m.id ? { ...x, isAdmin: true } : x)))
                              showToast(`已将 ${m.name} 设为${levelLabel}`)
                            }}
                            className={`${iconBtn} text-primary hover:bg-primary-light`}
                          >
                            <UserPlus size={14} />
                          </button>
                        )}
                        <button
                          type="button"
                          title={`把题库转让给 ${m.name}`}
                          onClick={() => setTransferTarget({ id: m.id, name: m.name })}
                          className={`${iconBtn} text-violet-500 hover:bg-violet-50`}
                        >
                          <ArrowLeftRight size={14} />
                        </button>
                        <button
                          type="button"
                          title="移出题库"
                          onClick={async () => {
                            try {
                              await bankMock.removeMember(bank.id, m.id)
                              setMembers((prev) => prev.filter((x) => x.id !== m.id))
                              showToast(`已将 ${m.name} 移出题库`)
                              onChanged()
                            } catch (err) {
                              showToast(err instanceof Error ? err.message : '操作失败')
                            }
                          }}
                          className={`${iconBtn} text-red-500 hover:bg-red-50`}
                        >
                          <UserX size={14} />
                        </button>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
            <p className="text-xs text-ink-3">成员操作：设为管理员、取消管理员、转让题库、移出题库（悬停图标查看）</p>
          </section>

          {/* 文档列表 */}
          <section className="space-y-2.5">
            <SectionTitle icon={FileUp}>已上传文档（{docs.length}）</SectionTitle>
            {docs.length === 0 && <p className="text-xs text-ink-3">暂无文档，可在下方上传</p>}
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
                  <button
                    type="button"
                    title="删除文档"
                    onClick={async () => {
                      await bankMock.removeDoc(bank.id, d.id)
                      setDocs((prev) => prev.filter((x) => x.id !== d.id))
                      onChanged()
                    }}
                    className="rounded p-1 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-500"
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
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

            {/* 上传与向量化进度 */}
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
                <p className="mt-1 text-[11px] text-ink-3">
                  {upload.phase === 'vector' ? '正在对文档内容做切片与向量索引' : '正在上传至题库'}
                </p>
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
            onClick={save}
            className="rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6]"
          >
            保存
          </button>
        </div>
      </div>

      {transferTarget && (
        <ConfirmDialog
          title="确认转让题库"
          message={`转让后你将失去管理员权限，该题库移入「我加入的题库」。确定转让给「${transferTarget.name}」吗？`}
          confirmText="确认转让"
          danger={false}
          onConfirm={async () => {
            await bankMock.transferBank(bank.id, transferTarget.id)
            showToast(`题库已转让给 ${transferTarget.name}`)
            onChanged()
            onClose()
          }}
          onClose={() => setTransferTarget(null)}
        />
      )}
    </div>
  )
}
