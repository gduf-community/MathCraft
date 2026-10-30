/** 题库管理页：我创建的题库 / 我加入的题库 两个标签页；真实知识库连接位于设置。 */
import { useCallback, useEffect, useState } from 'react'
import {
  ClipboardList,
  Folder,
  FolderPlus,
  Loader2,
  Pencil,
  Search,
  Trash2,
  UserMinus,
  Users,
} from 'lucide-react'
import * as bankMock from '../../../api/mock/bankMock'
import type { ManagedBank } from '../../../api/mock/bankMock'
import { useApp } from '../../../store/AppContext'
import { Avatar } from './shared'
import BankEditModal from './BankEditModal'
import BankViewModal from './BankViewModal'
import ConfirmDialog from './ConfirmDialog'

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

export default function BankTab() {
  const { showToast } = useApp()
  const [tab, setTab] = useState<SubTab>('owned')
  const [owned, setOwned] = useState<ManagedBank[]>([])
  const [joined, setJoined] = useState<ManagedBank[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [editTarget, setEditTarget] = useState<ManagedBank | null>(null)
  const [viewTarget, setViewTarget] = useState<ManagedBank | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ManagedBank | null>(null)
  const [quitTarget, setQuitTarget] = useState<ManagedBank | null>(null)
  const [joining, setJoining] = useState(false)

  const refresh = useCallback(async () => {
    const [o, j] = await Promise.all([bankMock.listOwned(), bankMock.listJoined()])
    setOwned(o)
    setJoined(j)
  }, [])

  useEffect(() => {
    void refresh().finally(() => setLoading(false))
  }, [refresh])

  const join = async () => {
    const code = search.trim()
    if (!code) {
      showToast('请输入要加入的题库编号')
      return
    }
    setJoining(true)
    try {
      const bank = await bankMock.joinByCode(code)
      showToast(`已加入题库「${bank.name}」`)
      setSearch('')
      await refresh()
    } catch (err) {
      showToast(err instanceof Error ? err.message : '加入失败')
    } finally {
      setJoining(false)
    }
  }

  const filteredOwned = owned.filter((b) => b.name.includes(search.trim()))

  const rowButton = 'inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors'
  const editBtn = `${rowButton} border border-primary/30 bg-primary-light/50 text-primary hover:bg-primary-light`
  const dangerBtn = `${rowButton} border border-red-200 bg-red-50 text-red-500 hover:bg-red-100`

  return (
    <div className="flex-1 overflow-y-auto bg-page p-3 sm:p-5">
      <p className="mb-4 text-xs text-ink-2">题库协作与成员操作为演示，真实知识库及其引擎请在设置中管理。</p>
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
            <div className="flex items-center gap-2.5">
              <div className="relative">
                <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="请输入题库名称进行搜索"
                  className="w-56 rounded-lg border border-line py-2 pl-8 pr-3 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
                />
              </div>
              <button
                type="button"
                onClick={() => showToast('新建题库功能将在后端接入后开放（演示）')}
                className="inline-flex items-center gap-1 rounded-lg bg-primary px-3.5 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6]"
              >
                <FolderPlus size={15} /> 新建题库
              </button>
            </div>
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
              {!loading && filteredOwned.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-10 text-center text-sm text-ink-3">
                    {search ? '没有匹配的题库' : '还没有创建题库'}
                  </td>
                </tr>
              )}
              {filteredOwned.map((b) => (
                <tr key={b.id} className="border-b border-line/50 transition-colors last:border-0 hover:bg-page/50">
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-3">
                      <FolderIcon />
                      <span className="text-sm font-medium text-ink">{b.name}</span>
                    </div>
                  </td>
                  <td className="px-3 py-3.5 text-sm text-ink-2">{b.code}</td>
                  <td className="px-3 py-3.5">
                    <MemberCount count={b.memberCount} capacity={b.capacity} />
                  </td>
                  <td className="px-5 py-3.5">
                    <div className="flex items-center justify-end gap-2">
                      <button type="button" onClick={() => setEditTarget(b)} className={editBtn}>
                        <Pencil size={12} /> 编辑
                      </button>
                      <button type="button" onClick={() => setDeleteTarget(b)} className={dangerBtn}>
                        <Trash2 size={12} /> 删除
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
          <div className="flex items-center justify-end gap-2.5 px-5 pt-4 pb-3">
            <div className="relative">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void join()
                }}
                placeholder="请输入题库编号进行搜索并加入"
                className="w-64 rounded-lg border border-line py-2 pl-8 pr-3 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
              />
            </div>
            <button
              type="button"
              onClick={() => void join()}
              disabled={joining}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6] disabled:opacity-60"
            >
              {joining ? <Loader2 size={14} className="animate-spin" /> : '加入'}
            </button>
          </div>

          <table className="w-full">
            <thead>
              <tr className="border-y border-line/70 bg-page/60 text-left text-xs text-ink-3">
                <th className="px-5 py-2.5 font-normal">题库名称</th>
                <th className="px-3 py-2.5 font-normal">题库编号</th>
                <th className="px-3 py-2.5 font-normal">人数</th>
                <th className="px-3 py-2.5 font-normal">创建者</th>
                <th className="px-5 py-2.5 text-right font-normal">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={5} className="py-10 text-center text-sm text-ink-3">
                    <Loader2 size={16} className="mr-2 inline animate-spin" />
                    正在加载题库…
                  </td>
                </tr>
              )}
              {!loading && joined.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-10 text-center text-sm text-ink-3">
                    还没有加入任何题库，输入编号即可加入
                  </td>
                </tr>
              )}
              {joined.map((b) => (
                <tr key={b.id} className="border-b border-line/50 transition-colors last:border-0 hover:bg-page/50">
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-3">
                      <FolderIcon />
                      <span className={`text-sm font-medium ${b.quitted ? 'text-ink-3' : 'text-ink'}`}>{b.name}</span>
                    </div>
                  </td>
                  <td className="px-3 py-3.5 text-sm text-ink-2">{b.code}</td>
                  <td className="px-3 py-3.5">
                    <MemberCount count={b.memberCount} capacity={b.capacity} />
                  </td>
                  <td className="px-3 py-3.5">
                    <div className="flex items-center gap-2">
                      <Avatar name={b.creator} size="sm" />
                      <span className="text-sm text-ink-2">{b.creator}</span>
                    </div>
                  </td>
                  <td className="px-5 py-3.5">
                    <div className="flex items-center justify-end gap-2">
                      <button type="button" onClick={() => setViewTarget(b)} className={editBtn}>
                        <Pencil size={12} /> 查看
                      </button>
                      {b.quitted ? (
                        <button type="button" disabled className={`${dangerBtn} cursor-not-allowed opacity-60`}>
                          已退出
                        </button>
                      ) : (
                        <button type="button" onClick={() => setQuitTarget(b)} className={dangerBtn}>
                          <UserMinus size={12} /> 退出
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 弹窗 */}
      {editTarget && (
        <BankEditModal
          bank={editTarget}
          onClose={() => setEditTarget(null)}
          onChanged={() => void refresh()}
        />
      )}
      {viewTarget && <BankViewModal bank={viewTarget} onClose={() => setViewTarget(null)} onChanged={() => void refresh()} />}
      {deleteTarget && (
        <ConfirmDialog
          title="删除题库"
          message={`确定删除题库「${deleteTarget.name}」吗？题库内的文档与索引将一并移除，操作不可恢复。`}
          confirmText="确认删除"
          onConfirm={async () => {
            await bankMock.deleteBank(deleteTarget.id)
            showToast(`题库「${deleteTarget.name}」已删除`)
            await refresh()
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
            await bankMock.quitBank(quitTarget.id)
            showToast(`已退出题库「${quitTarget.name}」`)
            await refresh()
          }}
          onClose={() => setQuitTarget(null)}
        />
      )}
    </div>
  )
}
