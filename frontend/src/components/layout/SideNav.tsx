import type { LucideIcon } from 'lucide-react'
import { BookOpen, Database, FileText, Home, PanelLeftClose, PanelLeftOpen, Settings, Star, User } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import type { TabKey } from '../../store/AppContext'

const NAV_ITEMS: { key: string; label: string; icon: LucideIcon; tab?: TabKey }[] = [
  { key: 'home', label: '智能出题', icon: Home, tab: 'generate' },
  { key: 'space', label: '学习空间', icon: BookOpen, tab: 'space' },
  { key: 'fav', label: '题目收藏', icon: Star },
  { key: 'paper', label: '组卷记录', icon: FileText },
  { key: 'bank', label: '题库管理', icon: Database, tab: 'bank' },
  { key: 'me', label: '个人中心', icon: User, tab: 'profile' },
]

export default function SideNav() {
  const { navCollapsed, toggleNav, showToast, activeTab, setActiveTab } = useApp()
  return (
    <nav
      aria-label="主导航"
      className={`app-side-nav z-10 flex shrink-0 flex-col border-r border-line/60 bg-white py-3 transition-all duration-300 ${
        navCollapsed ? 'w-16' : 'w-[168px]'
      }`}
    >
      <ul className="flex-1 space-y-1 px-2">
        {NAV_ITEMS.map(({ key, label, icon: Icon, tab }) => {
          const active = tab !== undefined && activeTab === tab
          return (
            <li key={key}>
              <button
                type="button"
                title={label}
                aria-label={label}
                aria-current={active ? 'page' : undefined}
                onClick={() => {
                  if (tab) {
                    setActiveTab(tab)
                  } else {
                    showToast('该模块暂未开放，当前可使用智能出题、题库管理、个人中心与设置')
                  }
                }}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
                  active
                    ? 'bg-primary-light font-semibold text-primary'
                    : 'text-ink-2 hover:bg-primary-weak hover:text-primary'
                } ${navCollapsed ? 'justify-center px-0' : ''}`}
              >
                <Icon size={18} className="shrink-0" />
                {!navCollapsed && <span className="nav-label truncate">{label}</span>}
              </button>
            </li>
          )
        })}
      </ul>
      <div className="space-y-1 border-t border-line/60 px-2 pt-2">
        <button type="button" title="设置" aria-label="设置" aria-current={activeTab === 'settings' ? 'page' : undefined} onClick={() => setActiveTab('settings')} className={
          'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ' + (activeTab === 'settings' ? 'bg-primary-light font-semibold text-primary' : 'text-ink-2 hover:bg-primary-weak hover:text-primary') + (navCollapsed ? ' justify-center px-0' : '')
        }><Settings size={18} className="shrink-0" />{!navCollapsed && <span className="nav-label">设置</span>}</button>
        <button
          type="button"
          onClick={toggleNav}
          title={navCollapsed ? '展开导航' : '收起导航'}
          className="flex h-9 w-full items-center justify-center gap-2 rounded-lg text-ink-3 transition-colors hover:bg-primary-weak hover:text-primary"
        >
          {navCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          {!navCollapsed && <span className="nav-label text-xs">收起导航</span>}
        </button>
      </div>
    </nav>
  )
}
