import { Bell, GraduationCap, LogOut } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { useAuth } from '../../store/AuthContext'

export default function TopBar() {
  const { profile, showToast } = useApp()
  const { user, logout } = useAuth()
  return (
    <header className="z-20 flex h-14 shrink-0 items-center justify-between border-b border-line/80 bg-white px-5">
      <div className="flex items-center gap-2">
        <GraduationCap size={26} strokeWidth={2.2} className="text-primary" />
        <h1 className="text-[20px] font-bold tracking-wide text-ink">MathCraft</h1>
      </div>
      <div className="flex items-center gap-4">
        <button
          type="button"
          title="通知"
          className="rounded-full p-1.5 text-ink-2 transition-colors hover:bg-primary-weak hover:text-primary"
        >
          <Bell size={18} />
        </button>
        <div className="h-5 w-px bg-line" />
        <button
          type="button"
          className="flex items-center gap-2 rounded-full py-1 pl-1 pr-2 transition-colors hover:bg-primary-weak"
        >
          {profile.avatar ? (
            <img
              src={profile.avatar}
              alt={`${profile.identity}头像`}
              className="h-8 w-8 rounded-full border border-line/60 object-cover"
            />
          ) : (
            <span className="flex h-8 w-8 items-center justify-center rounded-full border border-line/60 bg-primary-light text-sm font-semibold text-primary">
              {profile.name.charAt(0)}
            </span>
          )}
          <span className="text-sm text-ink">{profile.name}</span>
          <span className="rounded bg-primary-light px-1.5 py-0.5 text-xs text-primary">{profile.identity}</span>
        </button>
        <button
          type="button"
          title="退出登录"
          aria-label="退出登录"
          onClick={() => {
            logout()
            showToast(`已退出${user?.role === 'student' ? '学生' : '教师'}账号`)
          }}
          className="rounded-full p-1.5 text-ink-2 transition-colors hover:bg-red-50 hover:text-red-500"
        >
          <LogOut size={17} />
        </button>
      </div>
    </header>
  )
}
