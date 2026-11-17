/** 题库管理页：我创建的题库 / 我加入的题库 两个标签页 */
import { useCallback, useEffect, useState } from 'react'
import {
  Check,
  ClipboardList,
  Copy,
  Folder,
  FolderPlus,
  Loader2,
  Pencil,
  Trash2,
  Users,
} from 'lucide-react'
import * as bankApi from '../../../api/banks'
import type { ManagedBank } from '../../../api/banks'
import { useApp } from '../../../store/AppContext'
import { Avatar } from './shared'
import BankEditModal from './BankEditModal'
import BankCreateModal from './BankCreateModal'
import BankViewModal from './BankViewModal'
import ConfirmDialog from '../../ui/ConfirmDialog'

type SubTab = 'owned' | 'joined'

function FolderIcon() {
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-light">
      <Folder size={18} className="text-primary" />
    </span>
  )
}

function MemberCount({ count, capacity }: { count: number; capacity: number }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-ink-2">
      <Users size={15} className="text-ink-3" />
      {count}/{capacity}
    </span>
  )
}

/** 题库编号：点击复制到剪贴板 */
function BankCode({ code }: { code: string }) {
  const { showToast } = useApp()
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
    } catch {
      /* 剪贴板不可用时忽略 */
    }
    setCopied(true)
    showToast(`题库编号 ${code} 已复制`)
    window.setTimeout(() => setCopied(false), 1200)
  }
  return (
    <button
      type="button"
      title="点击复制题库编号"
      onClick={() => void copy()}
      className="inline-flex items-center gap-1 rounded px-1 font-mono text-sm text-ink-2 transition-colors hover:bg-primary-light hover:text-primary"
    >
      {code}
      {copied ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} className="text-ink-3" />}
    </button>
  )
}

export default function BankTab() {
  const { role, showToast, refreshKbs, invalidateDocument } = useApp()
  const canCreate = role === 'teacher'
  const [tab, setTab] = useState<SubTab>(canCreate ? 'owned' : 'joined')
  const [owned, setOwned] = useState<ManagedBank[]>([])
  const [joined, setJoined] = useState<ManagedBank[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [editTarget, setEditTarget] = useState<ManagedBank | null>(null)
  const [viewTarget, setViewTarget] = useState<ManagedBank | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ManagedBank | null>(null)
  const [quitTarget, setQuitTarget] = useState<ManagedBank | null>(null)

  const refresh = useCallback(async () => {
    const [o, j] = await Promise.all([bankApi.listOwned(), bankApi.listJoined()])
    setOwned(o)
    setJoined(j)
    setLoadError('')
    // 同步刷新智能出题侧边栏的「选择题库文档」选项
    await refreshKbs()
  }, [refreshKbs])

  useEffect(() => {
    void refresh().catch((err) => {
      setLoadError(err instanceof Error ? err.message : '刷新题库失败')
    }).finally(() => setLoading(false))
  }, [refresh])

  const refreshAfterChange = async (message = '刷新题库失败') => {
    try {
      await refresh()
    } catch (err) {
      const detail = `${message}：${err instanceof Error ? err.message : '请稍后重试'}`
      setLoadError(detail)
      showToast(detail)
    }
  }

  const rowButton = 'inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors'
  const editBtn = `${rowButton} border border-primary/30 bg-primary-light/50 text-primary hover:bg-primary-light`
  const dangerBtn = `${rowButton} border border-red-200 bg-red-50 text-red-500 hover:bg-red-100`

  return (
    <div className="flex-1 overflow-y-auto p-5">
      {loadError && <div role="alert" className="mb-3 flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
        <span>{loadError}</span>
        <button type="button" onClick={() => void refreshAfterChange()} className="shrink-0 rounded px-2 py-1 underline">重新读取</button>
      </div>}
      {/* 子标签页 */}
      <div className="flex items-center gap-7 border-b border-line px-1">
        {(
          [
            { key: 'owned', label: '我创建的题库', icon: ClipboardList },
            { key: 'joined', label: '我加入的题库', icon: Users },
          ] as const
        ).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`relative flex items-center gap-1.5 pb-3 pt-1 text-sm transition-colors ${
              tab === key ? 'font-semibold text-primary' : 'text-ink-2 hover:text-primary'
            }`}
          >
            <Icon size={16} />
            {label}
            {tab === key && <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-primary" />}
          </button>
        ))}
      </div>

      {/* 我创建的题库 */}
      {tab === 'owned' && (
        <div className="mt-4 rounded-xl border border-line/70 bg-white shadow-[0_4px_16px_rgba(30,90,180,0.05)]">
          <div className="flex items-center justify-between gap-4 px-5 pt-4 pb-3">
            <h3 className="text-sm font-bold text-ink">题库管理</h3>
            {canCreate && <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="inline-flex items-center gap-1 rounded-lg bg-primary px-3.5 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6]"
            >
              <FolderPlus size={15} /> 新建题库
            </button>}
          </div>

          <table className="w-full">
            <thead>
              <tr className="border-y border-line/70 bg-page/60 text-left text-xs text-ink-3">
                <th className="px-5 py-2.5 font-normal">题库名称</th>
                <th className="px-3 py-2.5 font-normal">题库编号</th>
                <th className="px-3 py-2.5 font-normal">人数</th>
                <th className="px-5 py-2.5 text-right font-normal">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={4} className="py-10 text-center text-sm text-ink-3">
                    <Loader2 size={16} className="mr-2 inline animate-spin" />
                    正在加载题库…
                  </td>
                </tr>
              )}
              {!loading && owned.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-10 text-center text-sm text-ink-3">
                    还没有创建题库
                  </td>
                </tr>
              )}
              {owned.map((b) => (
                <tr key={b.id} className="border-b border-line/50 transition-colors last:border-0 hover:bg-page/50">
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-3">
                      <FolderIcon />
                      <div className="min-w-0">
                        <span className="text-sm font-medium text-ink">{b.name}</span>
                        {b.status === 'deleting' && <>
                          <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">删除中</span>
                          <p className="mt-1 text-xs text-ink-3">{b.stage || '清理尚未完成，请继续清理'}</p>
                          {b.errorMessage && <p className="mt-1 break-words text-xs text-red-700">{b.errorMessage}</p>}
                        </>}
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-3.5">
                    <BankCode code={b.code} />
                  </td>
                  <td className="px-3 py-3.5">
                    <MemberCount count={b.memberCount} capacity={b.capacity} />
                  </td>
                  <td className="px-5 py-3.5">
                    <div className="flex items-center justify-end gap-2">
                      <button type="button" disabled={!b.canEdit || b.status === 'deleting'} onClick={async () => {
                        try {
                          setEditTarget(await bankApi.getBankDetail(b.id))
                        } catch (err) {
                          showToast(err instanceof Error ? err.message : '读取题库最新信息失败')
                        }
                      }} className={`${editBtn} disabled:cursor-not-allowed disabled:opacity-40`}>
                        <Pencil size={12} /> 编辑
                      </button>
                      <button type="button" disabled={!b.canDelete} onClick={() => setDeleteTarget(b)} className={`${dangerBtn} disabled:cursor-not-allowed disabled:opacity-40`}>
                        <Trash2 size={12} /> {b.status === 'deleting' ? '继续清理' : '删除'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

            {/* 我加入的题库 */}
      {tab === 'joined' && (
        <div className="mt-4 rounded-xl border border-line/70 bg-white shadow-[0_4px_16px_rgba(30,90,180,0.05)]">
          <div className="px-5 pt-4 pb-3 text-sm text-ink-3">题库成员由创建者在成员设置中添加，请联系创建者授权。</div>
          <table className="w-full">
            <thead><tr className="border-y border-line/70 bg-page/60 text-left text-xs text-ink-3"><th className="px-5 py-2.5 font-normal">题库名称</th><th className="px-3 py-2.5 font-normal">题库编号</th><th className="px-3 py-2.5 font-normal">人数</th><th className="px-3 py-2.5 font-normal">创建者</th><th className="px-5 py-2.5 text-right font-normal">操作</th></tr></thead>
            <tbody>
              {loading && <tr><td colSpan={5} className="py-10 text-center text-sm text-ink-3"><Loader2 size={16} className="mr-2 inline animate-spin" />正在加载题库…</td></tr>}
              {!loading && joined.length === 0 && <tr><td colSpan={5} className="py-10 text-center text-sm text-ink-3">还没有加入任何题库，请联系题库创建者添加</td></tr>}
              {joined.map((b) => <tr key={b.id} className="border-b border-line/50 last:border-0 hover:bg-page/50"><td className="px-5 py-3.5"><div className="flex items-center gap-3"><FolderIcon /><span className="text-sm font-medium text-ink">{b.name}</span></div></td><td className="px-3 py-3.5"><BankCode code={b.code} /></td><td className="px-3 py-3.5"><MemberCount count={b.memberCount} capacity={b.capacity} /></td><td className="px-3 py-3.5"><div className="flex items-center gap-2"><Avatar name={b.creator} size="sm" /><span className="text-sm text-ink-2">{b.creator}</span></div></td><td className="px-5 py-3.5 text-right"><button type="button" onClick={() => setViewTarget(b)} className={editBtn}><Pencil size={12} /> 查看</button></td></tr>)}
            </tbody>
          </table>
        </div>
      )}

      {/* 弹窗 */}
      {editTarget && (
        <BankEditModal
          bank={editTarget}
          onClose={() => setEditTarget(null)}
          onChanged={(deletedDocumentId) => {
            if (deletedDocumentId) invalidateDocument(editTarget.id, deletedDocumentId)
            void refreshAfterChange()
          }}
        />
      )}
      {viewTarget && <BankViewModal bank={viewTarget} onClose={() => setViewTarget(null)} onChanged={(deletedDocumentId) => {
        if (deletedDocumentId) invalidateDocument(viewTarget.id, deletedDocumentId)
        void refreshAfterChange()
      }} />}
      {canCreate && createOpen && <BankCreateModal onClose={() => setCreateOpen(false)} onChanged={() => void refreshAfterChange()} />}
      {deleteTarget && (
        <ConfirmDialog
          title={deleteTarget.status === 'deleting' ? '继续清理题库' : '删除题库'}
          message={`确定删除题库「${deleteTarget.name}」吗？题库内的文档与索引将一并移除，操作不可恢复。`}
          confirmText={deleteTarget.status === 'deleting' ? '继续清理' : '确认删除'}
          onConfirm={async () => {
            try {
              await bankApi.deleteBank(deleteTarget.id)
            } catch (err) {
              await refreshAfterChange('删除未完成，刷新题库失败')
              throw err
            }
            setOwned((prev) => prev.filter((bank) => bank.id !== deleteTarget.id))
            showToast(`题库「${deleteTarget.name}」已删除`)
            await refreshAfterChange('题库已删除，但刷新列表失败')
          }}
          onClose={() => setDeleteTarget(null)}
        />
      )}
      {quitTarget && (
        <ConfirmDialog
          title="退出题库"
          message={`确定退出题库「${quitTarget.name}」吗？退出后需重新申请加入。`}
          confirmText="确认退出"
          onConfirm={async () => {
            await bankApi.quitBankById(quitTarget.id)
            setJoined((prev) => prev.filter((bank) => bank.id !== quitTarget.id))
            showToast(`已退出题库「${quitTarget.name}」`)
            await refreshAfterChange('已退出题库，但刷新列表失败')
          }}
          onClose={() => setQuitTarget(null)}
        />
      )}
    </div>
  )
}
