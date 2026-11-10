import { ChartNoAxesCombined, Database, ShieldCheck, Users } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { changePasswordCurrent, validateNewPassword } from '../../api/auth'
import {
  createAdminAccount,
  fetchPlatformOverview,
  listAdminAccounts,
  resetAdminPassword,
  setAdminAccountStatus,
  updateAdminAccount,
} from '../../api/backend'
import type { AdminAccount, PlatformOverview } from '../../api/backend'
import { clearSession, getSessionGeneration } from '../../api/session'
import { useAuth } from '../../store/AuthContext'
import { useToast } from '../../store/ToastContext'
import { SecuritySettings } from '../tabs/ProfileTab/SecuritySettings'
import { RagSettingsPanel } from './RagSettingsPanel'

const ROLE_LABELS = { admin: '管理员', teacher: '教师', student: '学生' } as const
const NAV_ITEMS = [
  { id: 'overview', label: '平台概览', icon: ChartNoAxesCombined },
  { id: 'accounts', label: '账号管理', icon: Users },
  { id: 'rag', label: '模型与检索', icon: Database },
  { id: 'security', label: '账号安全', icon: ShieldCheck },
] as const
type AdminSection = typeof NAV_ITEMS[number]['id']

function validPassword(value: string): boolean {
  return validateNewPassword(value) === undefined
}

type RunAction = (
  action: () => Promise<unknown>, success: string, revokesSelf?: boolean,
) => Promise<boolean>

export default function AdminPanel() {
  const { user, logout, setAuthNotice } = useAuth()
  const { showToast } = useToast()
  const [section, setSection] = useState<AdminSection>('overview')
  const [ragDirty, setRagDirty] = useState(false)
  const [ragBusy, setRagBusy] = useState(false)
  const [accounts, setAccounts] = useState<AdminAccount[]>([])
  const [overview, setOverview] = useState<PlatformOverview | null>(null)
  const [query, setQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState<AdminAccount['role'] | ''>('')
  const [statusFilter, setStatusFilter] = useState<AdminAccount['status'] | ''>('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [createError, setCreateError] = useState('')
  const [securityError, setSecurityError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [sessionRevoked, setSessionRevoked] = useState(false)
  const [security, setSecurity] = useState({ current: '', password: '', confirmation: '' })
  const loadGeneration = useRef(0)
  const mutationBusy = useRef(false)
  const revoked = useRef(false)
  const mounted = useRef(false)
  const [form, setForm] = useState({
    account: '',
    display_name: '',
    role: 'teacher' as AdminAccount['role'],
    password: '',
  })

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; loadGeneration.current += 1 }
  }, [])

  useEffect(() => {
    if (revoked.current) return
    const generation = ++loadGeneration.current
    let active = true
    const load = async () => {
      setLoading(true)
      setLoadError('')
      try {
        const [nextAccounts, nextOverview] = await Promise.all([
          listAdminAccounts(query, roleFilter || undefined, statusFilter || undefined),
          fetchPlatformOverview(),
        ])
        if (!active || generation !== loadGeneration.current || revoked.current) return
        setAccounts(nextAccounts)
        setOverview(nextOverview)
      } catch (error: unknown) {
        if (active && generation === loadGeneration.current && !revoked.current) {
          setLoadError(error instanceof Error ? error.message : '加载失败')
        }
      } finally {
        if (active && generation === loadGeneration.current && !revoked.current) setLoading(false)
      }
    }
    void load()
    return () => { active = false }
  }, [query, roleFilter, statusFilter, refresh])

  const run: RunAction = async (action, success, revokesSelf = false) => {
    if (mutationBusy.current || revoked.current) return false
    mutationBusy.current = true
    setBusy(true)
    setMessage('')
    try {
      await action()
      if (!mounted.current || revoked.current) return false
      showToast(success, 'success')
      if (revokesSelf) {
        setMessage(success)
        revoked.current = true
        loadGeneration.current += 1
        setSessionRevoked(true)
      } else {
        setRefresh(value => value + 1)
      }
      return true
    } catch (error) {
      if (mounted.current) showToast(error instanceof Error ? error.message : '操作失败', 'error')
      return false
    } finally {
      mutationBusy.current = false
      if (mounted.current) setBusy(false)
    }
  }

  const submitCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setCreateError('')
    if (!validPassword(form.password)) {
      setCreateError('密码须为 8–64 字符，且 UTF-8 编码不超过 72 字节')
      return
    }
    if (await run(() => createAdminAccount(form), '账号已创建，请提醒用户登录后修改初始密码、按需绑定邮箱')) {
      setForm({ account: '', display_name: '', role: 'teacher', password: '' })
    }
  }

  const submitOwnPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSecurityError('')
    if (!validPassword(security.password) || security.password !== security.confirmation) {
      setSecurityError('请检查新密码长度、UTF-8 字节限制及两次输入是否一致')
      return
    }
    if (mutationBusy.current || revoked.current) return
    mutationBusy.current = true
    setBusy(true)
    setMessage('')
    const session = getSessionGeneration()
    try {
      await changePasswordCurrent(security.current, security.password, security.confirmation)
      if (getSessionGeneration() === session + 1) {
        setAuthNotice('密码已修改，全部会话已退出，请使用新密码重新登录')
      }
      // 认证 API 成功后清除当前会话，由 AuthContext 展示登录页。
    } catch (error: unknown) {
      if (mounted.current) showToast(error instanceof Error ? error.message : '修改密码失败', 'error')
    } finally {
      mutationBusy.current = false
      if (mounted.current) setBusy(false)
    }
  }

  function canLeaveRag(): boolean {
    if (section !== 'rag') return true
    if (ragBusy) {
      showToast('模型配置操作正在进行，请等待完成后再离开', 'error')
      return false
    }
    return !ragDirty || window.confirm('有未保存的模型配置，离开将丢弃修改。确定离开吗？')
  }

  function selectSection(next: AdminSection) {
    if (next !== section && canLeaveRag()) setSection(next)
  }

  if (sessionRevoked) return (
    <div className="min-h-screen bg-page p-6 text-ink">
      <section className="mx-auto max-w-lg rounded-2xl border border-line bg-white p-6">
        <h1 className="text-xl font-semibold">操作已完成</h1>
        <p className="mt-3" role="status">{message}。当前账号的全部会话已撤销，请重新登录；已禁用账号需由其他管理员恢复。</p>
        <button type="button" onClick={() => clearSession(false)} className="mt-4 rounded-lg bg-primary px-4 py-2 text-white">返回登录</button>
      </section>
    </div>
  )

  return (
    <div className="min-h-screen bg-page px-3 py-4 text-ink sm:px-6 sm:py-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-line bg-white px-5 py-5 shadow-sm">
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-primary">MathCraft 运维</p>
            <h1 className="mt-1 text-2xl font-bold">管理员面板</h1>
            <p className="mt-1 break-all text-sm text-ink-2">当前账号：{user?.displayName}</p>
          </div>
          <button type="button" disabled={ragBusy} onClick={() => { if (canLeaveRag()) void logout().catch((error: unknown) => showToast(error instanceof Error ? error.message : '退出未确认，请重试', 'error')) }} className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-ink-2 hover:bg-page disabled:opacity-60">
            退出登录
          </button>
        </header>

        <div className="grid min-w-0 gap-5 lg:grid-cols-[208px_minmax(0,1fr)]">
          <aside className="min-w-0 self-start rounded-2xl border border-line bg-white p-3 shadow-sm lg:sticky lg:top-6">
            <nav aria-label="管理员后台导航" className="grid min-w-0 grid-cols-2 gap-2 lg:grid-cols-1">
              {NAV_ITEMS.map(({ id, label, icon: Icon }) => <button key={id} type="button" disabled={ragBusy && id !== section} aria-current={section === id ? 'page' : undefined} aria-controls="admin-content" onClick={() => selectSection(id)} className={`flex min-h-11 min-w-0 items-center gap-2 rounded-xl px-3 py-3 text-left text-sm font-medium focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-60 ${section === id ? 'bg-primary-light text-primary' : 'text-ink-2 hover:bg-page'}`}><Icon size={18} aria-hidden="true" className="shrink-0" /><span>{label}</span></button>)}
            </nav>
          </aside>
          <main id="admin-content" className="min-w-0 space-y-5" aria-label={NAV_ITEMS.find(item => item.id === section)?.label}>

            <div hidden={section !== 'security'} className="space-y-5">

            <details className="rounded-xl border border-line bg-white p-5">
              <summary className="cursor-pointer text-sm font-semibold text-ink">个人账号安全</summary>
              <p className="my-4 break-all text-sm text-ink-2">当前登录账号：<span className="font-medium text-ink">{user?.username}</span></p>
              <SecuritySettings key={user?.userId} />
            </details>

            <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
              <h2 className="text-lg font-semibold">修改我的密码</h2>
              {user?.passwordChangeRecommended && <p role="status" className="mt-2 text-sm text-primary">你正在使用初始或管理员重置的密码，建议修改。此提醒不影响其他功能。</p>}
              <p className="mt-2 text-sm text-ink-3">新密码须为 8–64 字符，UTF-8 编码不超过 72 字节。修改成功后全部会话退出，请用新密码重新登录。</p>
              <form onSubmit={event => void submitOwnPassword(event)} className="mt-4 grid gap-3 md:grid-cols-4">
                <input aria-label="我的当前密码" type="password" autoComplete="current-password" value={security.current} onChange={event => setSecurity({ ...security, current: event.target.value })} placeholder="当前密码" required className="min-h-11 min-w-0 max-w-full rounded-lg border border-line px-3 py-2 text-sm" />
                <input aria-label="我的新密码" type="password" autoComplete="new-password" value={security.password} onChange={event => setSecurity({ ...security, password: event.target.value })} placeholder="新密码" required className="min-h-11 min-w-0 max-w-full rounded-lg border border-line px-3 py-2 text-sm" />
                <input aria-label="确认我的新密码" type="password" autoComplete="new-password" value={security.confirmation} onChange={event => setSecurity({ ...security, confirmation: event.target.value })} placeholder="确认新密码" required className="min-h-11 min-w-0 max-w-full rounded-lg border border-line px-3 py-2 text-sm" />
                <button type="submit" disabled={busy} className="rounded-lg bg-primary px-4 py-2 text-sm text-white disabled:opacity-60">验证当前密码并修改</button>
              </form>
              {securityError && <p role="alert" className="mt-3 text-sm text-danger">{securityError}</p>}
            </section>
            </div>

            {(section === 'overview' || section === 'accounts') && <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">{section === 'overview' ? '平台概览' : '账号管理'}</h2><button type="button" onClick={() => setRefresh(value => value + 1)} className="min-h-11 rounded-lg border border-line bg-white px-4 py-2 text-sm text-ink-2">{loading ? '刷新中…' : '刷新数据'}</button></div>}
            {(section === 'overview' || section === 'accounts') && loadError && <div role="alert" className="rounded-lg border border-line bg-white p-4 text-sm">数据刷新失败：{loadError} <button type="button" onClick={() => setRefresh(value => value + 1)} className="underline">重试</button></div>}

            {section === 'overview' && <>

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
                <div className="text-sm text-ink-3">持久化生成批次总数：{overview?.task_total ?? '—'}</div>
              </div>
              <p className="mt-2 text-sm text-ink-3">状态统计覆盖全部持久化生成批次；下表仅展示最近 50 条，不包含仅存于任务缓存的运行中或失败任务。完成时间未记录。</p>
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
                          <td className="px-3 py-2 text-ink-3">{task.completed_at ?? '未记录'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            </>}
            <div hidden={section !== 'accounts'} className="min-w-0 space-y-5">
            <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
              <h2 className="text-lg font-semibold">创建账号</h2>
              <p className="mt-2 text-sm text-ink-3">无需邮箱，用户使用登录账号进入。初始密码及重置密码须为 8–64 字符，UTF-8 编码不超过 72 字节；请提醒用户登录后修改。</p>
              <form className="mt-4 grid gap-3 md:grid-cols-5" onSubmit={(event) => void submitCreate(event)}>
                <input aria-label="登录账号" value={form.account} onChange={(event) => setForm({ ...form, account: event.target.value })} placeholder="登录账号" className="min-h-11 min-w-0 max-w-full rounded-lg border border-line px-3 py-2 text-sm" required />
                <input aria-label="显示名称" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} placeholder="显示名称" className="min-h-11 min-w-0 max-w-full rounded-lg border border-line px-3 py-2 text-sm" required />
                <select aria-label="角色" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as AdminAccount['role'] })} className="min-h-11 min-w-0 max-w-full rounded-lg border border-line px-3 py-2 text-sm">
                  <option value="teacher">教师</option><option value="student">学生</option><option value="admin">管理员</option>
                </select>
                <input aria-label="初始密码" type="password" autoComplete="new-password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} placeholder="初始密码" className="min-h-11 min-w-0 max-w-full rounded-lg border border-line px-3 py-2 text-sm" required />
                <button type="submit" disabled={busy} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">创建</button>
              </form>
              {createError && <p role="alert" className="mt-3 text-sm text-danger">{createError}</p>}
            </section>
            <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-semibold">账号管理</h2>
                <div className="flex flex-wrap gap-2">
                  <input aria-label="搜索账号" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索账号或显示名称" className="min-h-11 min-w-0 max-w-full rounded-lg border border-line px-3 py-2 text-sm" />
                  <select aria-label="按角色筛选" value={roleFilter} onChange={(event) => setRoleFilter(event.target.value as AdminAccount['role'] | '')} className="min-h-11 min-w-0 max-w-full rounded-lg border border-line px-3 py-2 text-sm">
                    <option value="">全部角色</option><option value="admin">管理员</option><option value="teacher">教师</option><option value="student">学生</option>
                  </select>
                  <select aria-label="按状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as AdminAccount['status'] | '')} className="min-h-11 min-w-0 max-w-full rounded-lg border border-line px-3 py-2 text-sm">
                    <option value="">全部状态</option><option value="active">启用</option><option value="disabled">禁用</option>
                  </select>
                </div>
              </div>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="border-b border-line text-ink-3"><tr><th className="px-3 py-2">账号</th><th className="px-3 py-2">名称</th><th className="px-3 py-2">角色</th><th className="px-3 py-2">状态</th><th className="px-3 py-2">操作</th></tr></thead>
                  <tbody>{!loading && !loadError && accounts.map((account) => <AccountRow key={account.id} account={account} currentUserId={user?.userId} busy={busy} onRun={run} />)}</tbody>
                </table>
                {loading && <p role="status" className="py-8 text-center text-sm text-ink-3">正在加载账号…</p>}
                {!loading && !loadError && accounts.length === 0 && <p className="py-8 text-center text-sm text-ink-3">没有匹配的账号</p>}
              </div>
            </section>
            </div>
            {section === 'rag' && <RagSettingsPanel onDirtyChange={setRagDirty} onBusyChange={setRagBusy} />}
          </main>
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return <div className="rounded-xl border border-line bg-white p-4 shadow-sm"><p className="text-sm text-ink-3">{label}</p><p className="mt-2 text-2xl font-semibold text-primary">{value}</p></div>
}

function AccountRow({ account, currentUserId, busy, onRun }: { account: AdminAccount; currentUserId: string | undefined; busy: boolean; onRun: RunAction }) {
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
          <button type="button" disabled={busy || !validPassword(password)} onClick={() => void (async () => {
            if (await onRun(() => resetAdminPassword(account.id, password), '密码已重置，请使用新密码登录并及时修改', account.id === currentUserId)) setPassword('')
          })()} className="rounded border border-line px-2 py-1 text-xs">重置密码</button>
          <button type="button" disabled={busy} onClick={() => void onRun(() => setAdminAccountStatus(account.id, account.status === 'active' ? 'disable' : 'restore'), account.status === 'active' ? '账号已禁用' : '账号已恢复', account.status === 'active' && account.id === currentUserId)} className="rounded border border-line px-2 py-1 text-xs">{account.status === 'active' ? '禁用' : '恢复'}</button>
        </div>
      </td>
    </tr>
  )
}
