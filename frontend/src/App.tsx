import { AppProvider, useApp } from './store/AppContext'
import TopBar from './components/layout/TopBar'
import SideNav from './components/layout/SideNav'
import ParamsSidebar from './components/layout/ParamsSidebar'
import TabBar from './components/layout/TabBar'
import GenerateTab from './components/tabs/GenerateTab'
import PreviewTab from './components/tabs/PreviewTab'
import BankTab from './components/tabs/BankTab'
import FavoritesTab from './components/tabs/FavoritesTab'
import Toast from './components/ui/Toast'
import { SettingsPage } from './components/settings/SettingsPage'
import { ProfilePage } from './components/profile/ProfilePage'
import { FavoritesProvider } from './store/FavoritesContext'
import { ProfileProvider } from './store/ProfileContext'
import { BookOpen } from 'lucide-react'

function Shell() {
  const { activeTab, settingsTarget } = useApp()
  return (
    <div className="flex h-screen flex-col bg-page text-ink">
      <TopBar />
      <div className="relative flex min-h-0 flex-1">
        <SideNav />
        <main className="z-10 mx-4 my-4 flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-line/70 bg-white shadow-[0_6px_24px_rgba(30,90,180,0.06)]">
          {activeTab === 'settings' ? <SettingsPage key={settingsTarget?.request ?? 0} initialEngine={settingsTarget?.engine} /> : activeTab === 'profile' ? <ProfilePage /> : activeTab === 'space' ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
              <span className="rounded-2xl bg-primary-light p-5 text-primary"><BookOpen size={36} /></span>
              <h2 className="text-xl font-bold">学习空间 · 即将开放</h2>
              <p className="max-w-md text-sm leading-7 text-ink-2">未来可在这里查看教师发布的题目并完成练习。目前仅向教师开放出题功能，学生接收与作答暂未开放。</p>
              <span className="rounded-full border border-line bg-page px-4 py-1.5 text-xs text-ink-2">当前为功能预告</span>
            </div>
          ) : activeTab === 'bank' ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <BankTab />
            </div>
          ) : activeTab === 'favorites' ? (
            <FavoritesTab />
          ) : (
            <>
              <TabBar />
              <div className="min-h-0 flex-1">{activeTab === 'generate' ? <GenerateTab /> : <PreviewTab />}</div>
            </>
          )}
        </main>
        {activeTab === 'generate' && <ParamsSidebar />}
      </div>
      <Toast />
    </div>
  )
}

export default function App() {
  return (
    <FavoritesProvider>
      <AppProvider>
        <ProfileProvider><Shell /></ProfileProvider>
      </AppProvider>
    </FavoritesProvider>
  )
}
