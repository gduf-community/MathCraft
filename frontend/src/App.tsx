import { AppProvider, useApp } from './store/AppContext'
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
import Toast from './components/ui/Toast'
import { SettingsPage } from './components/settings/SettingsPage'

function Shell() {
  const { activeTab, settingsTarget } = useApp()
  return (
    <div className="flex h-screen flex-col bg-page text-ink">
      <TopBar />
      <div className="relative flex min-h-0 flex-1">
        <SideNav />
        <main className="z-10 mx-4 my-4 flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-line/70 bg-white shadow-[0_6px_24px_rgba(30,90,180,0.06)]">
          {activeTab === 'settings' ? (
            <SettingsPage key={settingsTarget?.request ?? 0} initialEngine={settingsTarget?.engine} />
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
      <Toast />
    </div>
  )
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  )
}
