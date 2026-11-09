import { Bell, CheckCheck, GraduationCap, LogOut, X } from 'lucide-react'
import { useState } from 'react'
import { useApp } from '../../store/AppContext'
import { useAuth } from '../../store/AuthContext'
import ConfirmDialog from '../ui/ConfirmDialog'
import type { ApiUrge } from '../../api/backend'

/** 试卷剩余时间文案：不限时间 / 剩余 X / 已结束；不足 1 小时按分钟显示 */
function remainText(examEnd: string | null): string {
  if (!examEnd) return '不限时间'
  const diff = new Date(examEnd).getTime() - Date.now()
  if (diff <= 0) return '已结束'
  const days = Math.floor(diff / 86400000)
  if (days >= 1) return `${days} 天`
  const hours = Math.floor(diff / 3600000)
  if (hours >= 1) return `${hours} 小时`
  return `${Math.max(1, Math.floor(diff / 60000))} 分钟`
}

/** 通知弹窗：上半部分为题库入库通知（全员），下半部分为催交通知（学生） */
function UrgePanel({ onClose }: { onClose: () => void }) {
  const { urgeItems, urgeUnread, bankNotifItems, bankNotifUnread, clearUrgeBadge, clearBankNotifs, deleteBankNotif, markUrgeRead, deleteUrge, requestOpenSpacePaper } = useApp()
  const totalUnread = urgeUnread + bankNotifUnread
  const empty = urgeItems.length === 0 && bankNotifItems.length === 0
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-[#0f1b33]/45 p-4 pt-20" onClick={onClose}>
      <div
        className="flex max-h-[70vh] w-[520px] animate-pop flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <Bell size={18} className="text-primary" />
            <h3 className="text-base font-bold text-ink">通知</h3>
            {totalUnread > 0 && (
              <span className="rounded-full bg-red-500 px-1.5 py-0.5 text-[11px] font-bold leading-none text-white">
                {totalUnread}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                clearUrgeBadge()
                clearBankNotifs()
              }}
              title="清除红点"
              className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-xs text-ink-2 transition-colors hover:border-primary/50 hover:text-primary"
            >
              <CheckCheck size={13} />
              清除红点
            </button>
            <button type="button" onClick={onClose} className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink">
              <X size={18} />
            </button>
          </div>
        </div>
        <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto px-5 py-4">
          {empty && <li className="py-12 text-center text-sm text-ink-3">暂无通知</li>}
          {bankNotifItems.map((n) => (
            <li key={n.id} className="relative flex items-start gap-3 rounded-xl border border-line px-3.5 py-3 pr-9">
              {/* 单条删除：右上角 ×，与催交通知一致 */}
              <button
                type="button"
                title="删除该通知"
                onClick={() => deleteBankNotif(n.id)}
                className="absolute right-2 top-2 rounded p-0.5 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-500"
              >
                <X size={13} />
              </button>
              <span
                className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                  n.kind === 'bank_failed' ? 'bg-red-50 text-red-500' : 'bg-emerald-50 text-emerald-600'
                }`}
              >
                {n.kind === 'bank_failed' ? '入库失败' : '题库'}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm leading-6 text-ink">{n.body}</p>
                <p className="mt-0.5 text-xs text-ink-3">
                  {new Date(n.created_at).toLocaleString('zh-CN', { hour12: false })}
                </p>
              </div>
            </li>
          ))}
          {urgeItems.map((u: ApiUrge) => (
            <li key={u.id} className="relative flex items-center gap-3 rounded-xl border border-line px-3.5 py-3 pr-9">
              {/* 单条删除：右上角 ×，直接删除无需确认 */}
              <button
                type="button"
                title="删除该通知"
                onClick={() => deleteUrge(u.id)}
                className="absolute right-2 top-2 rounded p-0.5 text-ink-3 transition-colors hover:bg-red-50 hover:text-red-500"
              >
                <X size={13} />
              </button>
              <div className="min-w-0 flex-1">
                <p className="text-sm leading-6 text-ink">
                  {u.teacher_name}老师催你提交「{u.paper_name}」，该试卷剩余时间为{remainText(u.exam_end)}
                </p>
                <p className="mt-0.5 text-xs text-ink-3">
                  来自学习空间「{u.space_name}」 · {new Date(u.created_at).toLocaleString('zh-CN', { hour12: false })}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  // 跳转到对应空间的该试卷标签页，并消除该条红点
                  requestOpenSpacePaper(u.space_id, u.paper_id)
                  markUrgeRead(u.id)
                  onClose()
                }}
                className="shrink-0 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#1a5fe6]"
              >
                立即查看
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export default function TopBar() {
  const { profile, urgeUnread, bankNotifUnread, setActiveTab } = useApp()
  const { user, logout } = useAuth()
  const [bellOpen, setBellOpen] = useState(false)
  const [logoutConfirm, setLogoutConfirm] = useState(false)
  const totalUnread = urgeUnread + bankNotifUnread
  return (
    <header className="workspace-topbar z-20 flex h-14 shrink-0 items-center justify-between border-b border-line/80 bg-white px-5">
      <div className="flex items-center gap-2">
        <GraduationCap size={26} strokeWidth={2.2} className="text-primary" />
        <h1 className="text-[20px] font-bold tracking-wide text-ink">MathCraft</h1>
      </div>
      <div className="flex items-center gap-4">
        <button
          type="button"
          title="通知"
          aria-label="通知"
          onClick={() => setBellOpen(true)}
          className="relative rounded-full p-1.5 text-ink-2 transition-colors hover:bg-primary-weak hover:text-primary"
        >
          <Bell size={18} />
          {totalUnread > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold leading-none text-white">
              {totalUnread > 99 ? '99+' : totalUnread}
            </span>
          )}
        </button>
        <div className="h-5 w-px bg-line" />
        {/* 头像区域：点击进入个人中心 */}
        <button
          type="button"
          title="进入个人中心"
          onClick={() => setActiveTab('me')}
          className="flex items-center gap-2 rounded-full py-1 pl-1 pr-2 transition-colors hover:bg-primary-weak"
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-full border border-line/60 bg-primary-light text-sm font-semibold text-primary">
            {profile.name.charAt(0)}
          </span>
          <span className="text-sm text-ink">{profile.name}</span>
          <span className="rounded bg-primary-light px-1.5 py-0.5 text-xs text-primary">{profile.identity}</span>
        </button>
        <button
          type="button"
          title="退出登录"
          aria-label="退出登录"
          onClick={() => setLogoutConfirm(true)}
          className="rounded-full p-1.5 text-ink-2 transition-colors hover:bg-red-50 hover:text-red-500"
        >
          <LogOut size={17} />
        </button>
      </div>
      {bellOpen && <UrgePanel onClose={() => setBellOpen(false)} />}
      {logoutConfirm && (
        <ConfirmDialog
          title="退出登录"
          message={`确定退出当前${user?.role === 'student' ? '学生' : '教师'}账号「${profile.name}」吗？`}
          confirmText="确认退出"
          onConfirm={() => {
            void logout().catch(() => { window.alert('本地已退出，但服务端退出未确认。请在登录页点击“重试退出”，勿在共享设备继续使用。') })
          }}
          onClose={() => setLogoutConfirm(false)}
        />
      )}
    </header>
  )
}
