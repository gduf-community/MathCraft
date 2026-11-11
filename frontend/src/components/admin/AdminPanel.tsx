import { Activity, ChartNoAxesCombined, Database, HeartPulse, ShieldCheck, TriangleAlert, Users } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { changePasswordCurrent, validateNewPassword } from '../../api/auth'
import {
  createAdminAccount,
  listAdminAccounts,
  resetAdminPassword,
  setAdminAccountStatus,
  updateAdminAccount,
} from '../../api/backend'
import type { AdminAccount } from '../../api/backend'
import { clearSession, getSessionGeneration } from '../../api/session'
import { useAuth } from '../../store/AuthContext'
import { useToast } from '../../store/ToastContext'
import { SecuritySettings } from '../tabs/ProfileTab/SecuritySettings'
import { RagSettingsPanel } from './RagSettingsPanel'
import { LegacyOverview } from './LegacyOverview'
import { realOpsClient } from '../../api/adminOps'
import type { DemoScenario } from '../../api/adminOpsDemo'
import type { OpsClient, OpsQuery } from '../../types/ops'
import { AdminNotifications } from './ops/AdminNotifications'
import { AlertsPanel, DependenciesPanel, OpsOverviewPanel, RunsPanel } from './ops/OpsPages'
import { RunDrawer } from './ops/RunDrawer'

const ROLE_LABELS = { admin: '管理员', teacher: '教师', student: '学生' } as const
const NAV_ITEMS = [
  { id: 'overview', label: '平台概览', icon: ChartNoAxesCombined },
  { id: 'runs', label: '出题运行', icon: Activity },
  { id: 'dependencies', label: '依赖状态', icon: HeartPulse },
  { id: 'alerts', label: '异常中心', icon: TriangleAlert },
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
  const [opsClient, setOpsClient] = useState<OpsClient>(realOpsClient)
  const [demo, setDemo] = useState(false)
  const [scenario, setScenario] = useState<DemoScenario>('normal')
  const [opsSwitching, setOpsSwitching] = useState(false)
  const [sourceVersion, setSourceVersion] = useState(0)
  const [runQuery, setRunQuery] = useState<OpsQuery>()
  const [alertQuery, setAlertQuery] = useState<OpsQuery>()
  const [navigationVersion, setNavigationVersion] = useState(0)
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const sourceGeneration = useRef(0)
  const [ragDirty, setRagDirty] = useState(false)
  const [ragBusy, setRagBusy] = useState(false)
  const [accounts, setAccounts] = useState<AdminAccount[]>([])
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
    return () => {
      mounted.current = false
      loadGeneration.current += 1
      sourceGeneration.current += 1
    }
  }, [])

  useEffect(() => {
    if (revoked.current || section !== 'accounts') return
    const generation = ++loadGeneration.current
    const controller = new AbortController()
    let active = true
    const load = async () => {
      setLoading(true)
      setLoadError('')
      try {
        const nextAccounts = await listAdminAccounts(
          query, roleFilter || undefined, statusFilter || undefined, controller.signal,
        )
        if (!active || generation !== loadGeneration.current || revoked.current) return
        setAccounts(nextAccounts)
      } catch (error: unknown) {
        if (active && generation === loadGeneration.current && !revoked.current) {
          setLoadError(error instanceof Error ? error.message : '加载失败')
        }
      } finally {
        if (active && generation === loadGeneration.current && !revoked.current) setLoading(false)
      }
    }
    void load()
    return () => { active = false; controller.abort() }
  }, [query, roleFilter, statusFilter, refresh, section])

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
    if (next !== section && canLeaveRag()) {
      setSelectedRun(null)
      if (next === 'runs') setRunQuery(undefined)
      if (next === 'alerts') setAlertQuery(undefined)
      setSection(next)
    }
  }

  function openRuns(nextQuery?: OpsQuery) {
    if (!canLeaveRag()) return
    setSelectedRun(null)
    setRunQuery(nextQuery)
    setNavigationVersion(value => value + 1)
    setSection('runs')
  }

  function openAlerts(nextQuery?: OpsQuery) {
    if (!canLeaveRag()) return
    setSelectedRun(null)
    setAlertQuery(nextQuery)
    setNavigationVersion(value => value + 1)
    setSection('alerts')
  }

  async function changeOpsSource(nextDemo: boolean, nextScenario: DemoScenario = scenario) {
    if (!import.meta.env.DEV) return
    const generation = ++sourceGeneration.current
    setOpsSwitching(true)
    setSelectedRun(null)
    try {
      const nextClient = nextDemo
        ? (await import('../../api/adminOpsDemo')).createDemoOpsClient(nextScenario)
        : realOpsClient
      if (!mounted.current || generation !== sourceGeneration.current) return
      setOpsClient(nextClient)
      setDemo(nextDemo)
      setScenario(nextScenario)
      setRunQuery(undefined)
      setAlertQuery(undefined)
      setSourceVersion(value => value + 1)
    } catch (error: unknown) {
      if (mounted.current && generation === sourceGeneration.current) {
        showToast(error instanceof Error ? error.message : '演示模块加载失败', 'error')
      }
    } finally {
      if (mounted.current && generation === sourceGeneration.current) setOpsSwitching(false)
    }
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
            <h1 className="mt-1 text-2xl font-bold">运维后台</h1>
            <p className="mt-1 break-all text-sm text-ink-2">当前账号：{user?.displayName}</p>
          </div>
          <div className="flex items-center gap-2">
          {!opsSwitching && <AdminNotifications key={sourceVersion} client={opsClient}
            demo={demo} disabled={ragBusy} onOpenAlert={id => openAlerts({ alert_id: id })} />}
          <button type="button" disabled={ragBusy} onClick={() => { if (canLeaveRag()) void logout().catch((error: unknown) => showToast(error instanceof Error ? error.message : '退出未确认，请重试', 'error')) }} className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-ink-2 hover:bg-page disabled:opacity-60">
            退出登录
          </button>
          </div>
        </header>

        {import.meta.env.DEV && <section aria-label="运维演示设置"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/20 bg-primary-weak p-4 text-sm">
          <div className="min-w-0">
            <p className="font-semibold text-primary">{demo ? '运维观测 · 合成演示数据' : '运维观测 · 真实接口'}</p>
            <p className="mt-1 text-ink-2">演示仅覆盖运维统计、运行、依赖、异常和通知；账号、配置、安全及平台资源统计仍为真实操作与数据。</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex min-h-11 cursor-pointer items-center gap-2">
              <input type="checkbox" checked={demo} disabled={opsSwitching}
                onChange={event => void changeOpsSource(event.target.checked)} className="h-4 w-4 accent-primary" />
              使用演示数据
            </label>
            {demo && <label className="flex min-h-11 items-center gap-2">
              演示场景
              <select value={scenario} disabled={opsSwitching} className="min-h-11 rounded-lg border border-line bg-white px-3"
                onChange={event => {
                  const value = event.target.value
                  if (value === 'normal' || value === 'loading' || value === 'empty'
                    || value === 'partial' || value === 'error') void changeOpsSource(true, value)
                }}>
                <option value="normal">典型运行与异常</option>
                <option value="loading">缓慢加载</option>
                <option value="empty">空数据</option>
                <option value="partial">部分可用</option>
                <option value="error">服务不可用</option>
              </select>
            </label>}
          </div>
        </section>}

        <div className="grid min-w-0 gap-5 lg:grid-cols-[208px_minmax(0,1fr)]">
          <aside className="min-w-0 self-start rounded-2xl border border-line bg-white p-3 shadow-sm lg:sticky lg:top-6">
            <nav aria-label="管理员后台导航" className="grid min-w-0 grid-cols-2 gap-2 lg:grid-cols-1">
              {NAV_ITEMS.map(({ id, label, icon: Icon }) => <button key={id} type="button" disabled={ragBusy && id !== section} aria-current={section === id ? 'page' : undefined} aria-controls="admin-content" onClick={() => selectSection(id)} className={`flex min-h-11 min-w-0 items-center gap-2 rounded-xl px-3 py-3 text-left text-sm font-medium focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-60 ${section === id ? 'bg-primary-light text-primary' : 'text-ink-2 hover:bg-page'}`}><Icon size={18} aria-hidden="true" className="shrink-0" /><span>{label}</span></button>)}
            </nav>
          </aside>
          <main id="admin-content" className="min-w-0 space-y-5" aria-label={NAV_ITEMS.find(item => item.id === section)?.label}>

            {opsSwitching && <p role="status" className="rounded-xl border border-line bg-white p-5 text-sm text-ink-2">正在切换运维数据源…</p>}
            {!opsSwitching && section === 'runs' && <RunsPanel key={`${sourceVersion}:${navigationVersion}`}
              client={opsClient} initialQuery={runQuery} onOpenRun={setSelectedRun} />}
            {!opsSwitching && section === 'dependencies' && <DependenciesPanel key={sourceVersion}
              client={opsClient} onOpenRuns={openRuns} />}
            {!opsSwitching && section === 'alerts' && <AlertsPanel key={`${sourceVersion}:${navigationVersion}`}
              client={opsClient} initialQuery={alertQuery} onOpenRun={setSelectedRun} />}

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

            {section === 'accounts' && <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">账号管理</h2><button type="button" onClick={() => setRefresh(value => value + 1)} className="min-h-11 rounded-lg border border-line bg-white px-4 py-2 text-sm text-ink-2">{loading ? '刷新中…' : '刷新数据'}</button></div>}
            {section === 'accounts' && loadError && <div role="alert" className="rounded-lg border border-line bg-white p-4 text-sm">数据刷新失败：{loadError} <button type="button" onClick={() => setRefresh(value => value + 1)} className="underline">重试</button></div>}

            {section === 'overview' && <>
              {!opsSwitching && <OpsOverviewPanel key={sourceVersion} client={opsClient}
                onOpenRuns={openRuns} onOpenAlerts={openAlerts} />}
              <LegacyOverview />
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
      {!opsSwitching && selectedRun && <RunDrawer client={opsClient} runId={selectedRun}
        onClose={() => setSelectedRun(null)} onOpenAlerts={openAlerts} demo={demo} />}
    </div>
  )
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
