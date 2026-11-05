import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  createAdminAccount,
  fetchPlatformOverview,
  listAdminAccounts,
  resetAdminPassword,
  setAdminAccountStatus,
  updateAdminAccount,
} from '../../api/backend'
import type { AdminAccount, PlatformOverview } from '../../api/backend'
import { useAuth } from '../../store/AuthContext'

const ROLE_LABELS = { admin: '管理员', teacher: '教师', student: '学生' } as const

export default function AdminPanel() {
  const { user, logout } = useAuth()
  const [accounts, setAccounts] = useState<AdminAccount[]>([])
  const [overview, setOverview] = useState<PlatformOverview | null>(null)
  const [query, setQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState<AdminAccount['role'] | ''>('')
  const [statusFilter, setStatusFilter] = useState<AdminAccount['status'] | ''>('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [form, setForm] = useState({
    account: '',
    display_name: '',
    role: 'teacher' as AdminAccount['role'],
    password: '',
  })

  const load = useCallback(async () => {
    const [nextAccounts, nextOverview] = await Promise.all([
      listAdminAccounts(query, roleFilter || undefined, statusFilter || undefined),
      fetchPlatformOverview(),
    ])
    setAccounts(nextAccounts)
    setOverview(nextOverview)
  }, [query, roleFilter, statusFilter])

  useEffect(() => {
    void load().catch((error: unknown) => setMessage(error instanceof Error ? error.message : '加载失败'))
  }, [load])

  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    setMessage('')
    try {
      await action()
      await load()
      setMessage(success)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '操作失败')
    } finally {
      setBusy(false)
    }
  }

  const submitCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await run(() => createAdminAccount(form), '账号已创建')
    setForm({ account: '', display_name: '', role: 'teacher', password: '' })
  }

  return (
    <div className="min-h-screen bg-page px-6 py-6 text-ink">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="flex items-center justify-between rounded-2xl border border-line bg-white px-6 py-5 shadow-sm">
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-primary">MathCraft 运维</p>
            <h1 className="mt-1 text-2xl font-bold">管理员面板</h1>
            <p className="mt-1 text-sm text-ink-3">当前账号：{user?.displayName}</p>
          </div>
          <button type="button" onClick={logout} className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 hover:bg-page">
            退出登录
          </button>
        </header>

        {message && <div className="rounded-lg bg-primary-weak px-4 py-3 text-sm text-primary" role="status">{message}</div>}

        <section className="grid gap-4 sm:grid-cols-3">
          <StatCard label="教师" value={overview ? (overview.accounts.teacher_active ?? 0) + (overview.accounts.teacher_disabled ?? 0) : '—'} />
          <StatCard label="学生" value={overview ? (overview.accounts.student_active ?? 0) + (overview.accounts.student_disabled ?? 0) : '—'} />
          <StatCard label="管理员" value={overview ? (overview.accounts.admin_active ?? 0) + (overview.accounts.admin_disabled ?? 0) : '—'} />
          <StatCard label="题库／知识库" value={overview?.resources.banks ?? '—'} />
          <StatCard label="文档" value={overview?.resources.documents ?? '—'} />
          <StatCard label="试卷" value={overview?.resources.papers ?? '—'} />
        </section>

        <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">平台信息</h2>
              <p className="mt-1 text-sm text-ink-3">联系管理员：{overview?.admin_contact || '未配置'}</p>
            </div>
            <div className="text-sm text-ink-3">任务总数：{overview ? overview.tasks.length : '—'}</div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {overview && Object.entries(overview.task_status_counts).map(([status, count]) => (
              <span key={status} className="rounded-full bg-page px-3 py-1 text-xs text-ink-2">{status}：{count}</span>
            ))}
          </div>
          {overview && overview.tasks.length > 0 && (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="border-b border-line text-ink-3">
                  <tr><th className="px-3 py-2">任务类型</th><th className="px-3 py-2">状态</th><th className="px-3 py-2">创建时间</th><th className="px-3 py-2">完成时间</th></tr>
                </thead>
                <tbody>
                  {overview.tasks.map((task) => (
                    <tr key={task.id} className="border-b border-line/70 last:border-0">
                      <td className="px-3 py-2">{task.type}</td>
                      <td className="px-3 py-2">{task.status}</td>
                      <td className="px-3 py-2 text-ink-3">{task.created_at}</td>
                      <td className="px-3 py-2 text-ink-3">{task.completed_at ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold">创建账号</h2>
          <form className="mt-4 grid gap-3 md:grid-cols-5" onSubmit={(event) => void submitCreate(event)}>
            <input aria-label="登录账号" value={form.account} onChange={(event) => setForm({ ...form, account: event.target.value })} placeholder="登录账号" className="rounded-lg border border-line px-3 py-2 text-sm" required />
            <input aria-label="显示名称" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} placeholder="显示名称" className="rounded-lg border border-line px-3 py-2 text-sm" required />
            <select aria-label="角色" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as AdminAccount['role'] })} className="rounded-lg border border-line px-3 py-2 text-sm">
              <option value="teacher">教师</option><option value="student">学生</option><option value="admin">管理员</option>
            </select>
            <input aria-label="初始密码" type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} placeholder="初始密码" className="rounded-lg border border-line px-3 py-2 text-sm" minLength={6} required />
            <button type="submit" disabled={busy} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">创建</button>
          </form>
        </section>

        <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">账号管理</h2>
            <div className="flex flex-wrap gap-2">
              <input aria-label="搜索账号" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索账号或显示名称" className="rounded-lg border border-line px-3 py-2 text-sm" />
              <select aria-label="按角色筛选" value={roleFilter} onChange={(event) => setRoleFilter(event.target.value as AdminAccount['role'] | '')} className="rounded-lg border border-line px-3 py-2 text-sm">
                <option value="">全部角色</option><option value="admin">管理员</option><option value="teacher">教师</option><option value="student">学生</option>
              </select>
              <select aria-label="按状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as AdminAccount['status'] | '')} className="rounded-lg border border-line px-3 py-2 text-sm">
                <option value="">全部状态</option><option value="active">启用</option><option value="disabled">禁用</option>
              </select>
            </div>
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-line text-ink-3"><tr><th className="px-3 py-2">账号</th><th className="px-3 py-2">名称</th><th className="px-3 py-2">角色</th><th className="px-3 py-2">状态</th><th className="px-3 py-2">操作</th></tr></thead>
              <tbody>{accounts.map((account) => <AccountRow key={account.id} account={account} busy={busy} onRun={run} />)}</tbody>
            </table>
            {accounts.length === 0 && <p className="py-8 text-center text-sm text-ink-3">没有匹配的账号</p>}
          </div>
        </section>
      </div>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return <div className="rounded-xl border border-line bg-white p-4 shadow-sm"><p className="text-sm text-ink-3">{label}</p><p className="mt-2 text-2xl font-semibold text-primary">{value}</p></div>
}

function AccountRow({ account, busy, onRun }: { account: AdminAccount; busy: boolean; onRun: (action: () => Promise<unknown>, success: string) => Promise<void> }) {
  const [name, setName] = useState(account.display_name)
  const [password, setPassword] = useState('')
  return (
    <tr className="border-b border-line/70 last:border-0">
      <td className="px-3 py-3 font-medium">{account.account}</td>
      <td className="px-3 py-3"><input aria-label={`${account.account}显示名称`} value={name} onChange={(event) => setName(event.target.value)} className="w-32 rounded border border-line px-2 py-1" /></td>
      <td className="px-3 py-3">{ROLE_LABELS[account.role]}</td>
      <td className="px-3 py-3">{account.status === 'active' ? '启用' : '禁用'}</td>
      <td className="px-3 py-3">
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={() => void onRun(() => updateAdminAccount(account.id, name), '名称已更新')} className="rounded border border-line px-2 py-1 text-xs">保存名称</button>
          <input aria-label={`${account.account}新密码`} type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="新密码" className="w-24 rounded border border-line px-2 py-1 text-xs" />
          <button type="button" disabled={busy || password.length < 6} onClick={() => void onRun(() => resetAdminPassword(account.id, password), '密码已重置')} className="rounded border border-line px-2 py-1 text-xs">重置密码</button>
          <button type="button" disabled={busy} onClick={() => void onRun(() => setAdminAccountStatus(account.id, account.status === 'active' ? 'disable' : 'restore'), account.status === 'active' ? '账号已禁用' : '账号已恢复')} className="rounded border border-line px-2 py-1 text-xs">{account.status === 'active' ? '禁用' : '恢复'}</button>
        </div>
      </td>
    </tr>
  )
}
