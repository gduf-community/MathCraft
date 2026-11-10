import { AppProvider, useApp } from './store/AppContext'
import { AuthProvider, useAuth } from './store/AuthContext'
import { ToastProvider } from './store/ToastContext'
import TopBar from './components/layout/TopBar'
import SideNav from './components/layout/SideNav'
import ParamsSidebar from './components/layout/ParamsSidebar'
import TabBar from './components/layout/TabBar'
import GenerateTab from './components/tabs/GenerateTab'
import PreviewTab from './components/tabs/PreviewTab'
import BankTab from './components/tabs/BankTab'
import RecordsTab from './components/tabs/RecordsTab'
import FavoritesTab from './components/tabs/FavoritesTab'
import SpaceTab from './components/tabs/SpaceTab'
import ProfileTab from './components/tabs/ProfileTab'
import { SettingsPage } from './components/settings/SettingsPage'
import Toast from './components/ui/Toast'
import LoginPage from './components/auth/LoginPage'
import AdminPanel from './components/admin/AdminPanel'

function Shell() {
  const { activeTab, setActiveTab } = useApp()
  const { user } = useAuth()
  return (
    <div className="workspace-shell flex h-screen animate-fade-in flex-col bg-page text-ink">
      <TopBar />
      {user?.passwordChangeRecommended && <div className="flex items-center justify-center gap-3 bg-primary-weak px-4 py-2 text-sm text-primary" role="status">
        <span>当前密码由管理员设置，建议登录后修改。</span>
        <button type="button" className="underline" onClick={() => setActiveTab('me')}>前往个人中心修改</button>
      </div>}
      <div className="workspace-body relative flex min-h-0 flex-1">
        <SideNav />
        <main className="z-10 mx-4 my-4 flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-line/70 bg-white shadow-[0_6px_24px_rgba(30,90,180,0.06)]">
          {activeTab === 'settings' ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <SettingsPage />
            </div>
          ) : activeTab === 'bank' ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <BankTab />
            </div>
          ) : activeTab === 'records' ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <RecordsTab />
            </div>
          ) : activeTab === 'fav' ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <FavoritesTab />
            </div>
          ) : activeTab === 'space' ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <SpaceTab />
            </div>
          ) : activeTab === 'me' ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <ProfileTab />
            </div>
          ) : (
            <>
              <TabBar />
              <div className="min-h-0 flex-1">{activeTab === 'generate' ? <GenerateTab /> : <PreviewTab />}</div>
            </>
          )}
        </main>
        {activeTab === 'generate' && <ParamsSidebar />}
      </div>
    </div>
  )
}

/** 登录门禁：未登录渲染登录页（登录成功整页淡出），已登录挂载主应用并淡入 */
function AuthGate() {
  const { user, restoring } = useAuth()
  if (restoring) return <div className="flex min-h-screen items-center justify-center bg-page text-ink" role="status">正在恢复安全会话…</div>
  if (!user) return <LoginPage />
  if (user.role === 'admin') return <AdminPanel />
  return (
    <AppProvider key={`${user.userId}:${user.role}`}>
      <Shell />
    </AppProvider>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <AuthGate />
        <Toast />
      </ToastProvider>
    </AuthProvider>
  )
}
