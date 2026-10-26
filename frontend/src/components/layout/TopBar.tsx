import { Bell, ChevronDown, GraduationCap } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { useProfile } from '../../store/ProfileContext'
import { apiUrl } from '../../api/settingsHttp'

export default function TopBar() {
  const { setActiveTab, showToast } = useApp()
  const { profile } = useProfile()
  return (
    <header className="z-20 flex h-14 shrink-0 items-center justify-between border-b border-line/80 bg-white px-3 sm:px-5">
      <div className="flex items-center gap-2">
        <GraduationCap size={26} strokeWidth={2.2} className="text-primary" />
        <h1 className="text-[20px] font-bold tracking-wide text-ink">出题智能体</h1>
      </div>
      <div className="flex items-center gap-4">
        <button
          type="button"
          title="通知"
          aria-label="通知"
          onClick={() => showToast('通知功能暂未开放')}
          className="rounded-full p-1.5 text-ink-2 transition-colors hover:bg-primary-weak hover:text-primary"
        >
          <Bell size={18} />
        </button>
        <div className="h-5 w-px bg-line" />
        <button
          type="button"
          aria-label="打开个人中心"
          onClick={() => setActiveTab('profile')}
          className="flex items-center gap-2 rounded-full py-1 pl-1 pr-2 transition-colors hover:bg-primary-weak"
        >
          <span className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full bg-primary text-sm font-semibold text-white">
            {profile?.avatar_url ? <img className="h-full w-full object-cover" src={apiUrl(profile.avatar_url)} alt="" /> : (profile?.nickname[0] || '师')}
          </span>
          <span className="hidden max-w-28 truncate text-sm text-ink sm:inline">{profile?.nickname || '教师'}</span>
          <span className="rounded bg-primary-light px-1.5 py-0.5 text-xs text-primary">教师</span>
          <ChevronDown size={15} className="text-ink-3" />
        </button>
      </div>
    </header>
  )
}
