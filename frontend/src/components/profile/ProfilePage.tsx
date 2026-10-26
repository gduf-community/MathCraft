import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Camera, GraduationCap, Loader2, Save, UserRound } from 'lucide-react'
import { apiUrl, settingsRequest } from '../../api/settingsHttp'
import { useApp } from '../../store/AppContext'
import { useProfile } from '../../store/ProfileContext'
import type { ProfileUpdate, UserProfile } from '../../types/profile'

const STAGES = [{ value: 'primary', label: '小学' }, { value: 'junior', label: '初中' }, { value: 'senior', label: '高中' }] as const
const GRADES: Record<string, string[]> = {
  primary: ['1', '2', '3', '4', '5', '6'],
  junior: ['7', '8', '9'],
  senior: ['10', '11', '12'],
}

function profileFields({ nickname, teaching_stage, grade }: UserProfile): ProfileUpdate {
  return { nickname, teaching_stage, grade }
}

function gradeLabel(value: string): string {
  const number = Number(value)
  return number >= 10 ? ['高一', '高二', '高三'][number - 10] : value + '年级'
}

export function ProfilePage() {
  const { profile, loading, error: loadError, refresh, updateProfile } = useProfile()
  const { setHasUnsavedChanges, showToast } = useApp()
  const [form, setForm] = useState<ProfileUpdate | null>(null)
  const [baseline, setBaseline] = useState('')
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [pendingAvatar, setPendingAvatar] = useState<{ file: File; previewUrl: string } | null>(null)
  const saving = useRef(false)
  const [error, setError] = useState('')
  const errorRef = useRef<HTMLDivElement>(null)
  const uploadInput = useRef<HTMLInputElement>(null)
  const dirty = pendingAvatar !== null || (form !== null && JSON.stringify(form) !== baseline)

  useEffect(() => {
    if (!pendingAvatar) return
    return () => URL.revokeObjectURL(pendingAvatar.previewUrl)
  }, [pendingAvatar])

  useEffect(() => {
    if (!profile) return
    const next = profileFields(profile)
    setForm(next)
    setBaseline(JSON.stringify(next))
  }, [profile?.nickname, profile?.teaching_stage, profile?.grade])
  useEffect(() => {
    setHasUnsavedChanges(dirty || busy || uploading)
    return () => setHasUnsavedChanges(false)
  }, [dirty, busy, uploading, setHasUnsavedChanges])
  useEffect(() => { if (error) errorRef.current?.focus() }, [error])

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!form || saving.current) return
    saving.current = true
    setError('')
    setBusy(true)
    try {
      const saved = await settingsRequest<UserProfile>('/api/user-profile', { method: 'PUT', body: JSON.stringify(form) })
      updateProfile(saved)
      const next = profileFields(saved)
      setForm(next)
      setBaseline(JSON.stringify(next))
      if (pendingAvatar) {
        setUploading(true)
        try {
          const data = new FormData()
          data.append('file', pendingAvatar.file)
          const withAvatar = await settingsRequest<UserProfile>('/api/user-profile/avatar', { method: 'POST', body: data })
          updateProfile(withAvatar)
          setPendingAvatar(null)
        } catch (cause) {
          const message = cause instanceof Error ? cause.message : '请重试'
          setError(`个人资料已保存，但头像上传失败：${message}。待确认头像已保留，可再次点击保存资料重试，或恢复已保存资料。`)
          return
        } finally { setUploading(false) }
      }
      showToast('个人资料已保存')
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '请重试'
      setError(`个人资料保存失败：${message}。未上传头像，待确认编辑已保留。`)
    } finally { saving.current = false; setBusy(false) }
  }
  const selectAvatar = (file: File) => {
    if (saving.current) return
    setError('')
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size === 0 || file.size > 5 * 1024 * 1024) {
      setError('请选择非空且 5 MiB 以内的 PNG、JPEG 或 WebP 图片。')
      return
    }
    setPendingAvatar({ file, previewUrl: URL.createObjectURL(file) })
  }
  const restore = () => {
    if (!profile || saving.current) return
    const next = profileFields(profile)
    setForm(next)
    setBaseline(JSON.stringify(next))
    setPendingAvatar(null)
    setError('')
    if (uploadInput.current) uploadInput.current.value = ''
  }

  if (loading && !profile) return <div className="p-8 text-ink-2" role="status">正在读取个人资料…</div>
  if (!profile || !form) return <div className="p-8"><div className="settings-error" role="alert">{loadError || '无法读取个人资料'}</div><button className="settings-button-secondary mt-4" onClick={() => void refresh()}>重新加载</button></div>
  const gradeOptions = GRADES[form.teaching_stage]
  return <div className="min-h-0 flex-1 overflow-y-auto bg-page/60 p-4 sm:p-7">
    <div className="mx-auto max-w-3xl">
      <h2 className="text-xl font-bold">个人中心</h2>
      <p className="mb-6 mt-1 text-sm text-ink-2">维护你的教师资料。</p>
      {error && <div className="settings-error mb-4" role="alert" tabIndex={-1} ref={errorRef}>{error}</div>}
      <div className="settings-card mb-5 flex flex-wrap items-center gap-5">
        <div className="flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-primary-light text-primary">
          {pendingAvatar || profile.avatar_url ? <img src={pendingAvatar?.previewUrl ?? apiUrl(profile.avatar_url ?? '')} alt={pendingAvatar ? "待保存头像预览" : "当前头像"} className="h-full w-full object-cover" /> : <UserRound size={36} />}
        </div>
        <div className="min-w-0 flex-1"><h3 className="truncate text-lg font-semibold">{profile.nickname}</h3><p className="mt-1 flex items-center gap-1.5 text-sm text-primary"><GraduationCap size={16} />教师</p></div>
        <div><button type="button" className="settings-button-secondary" disabled={busy || uploading} onClick={() => uploadInput.current?.click()}>{uploading ? <Loader2 className="animate-spin" size={16} /> : <Camera size={16} />}更换头像</button>
          <p className="mt-2 text-xs text-ink-2">PNG / JPEG / WebP · 最大 5 MiB<br />{pendingAvatar ? '当前仅为本地预览，点击保存资料后上传' : '选择后可预览，随保存资料确认'}</p>
          <input ref={uploadInput} className="hidden" aria-label="上传头像" type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) selectAvatar(file); event.target.value = '' }} />
        </div>
      </div>
      <form onSubmit={(event) => void save(event)} className="settings-card space-y-5">
        <h3 className="text-base font-semibold">基本资料</h3>
        <fieldset disabled={busy || uploading} className="grid gap-5 sm:grid-cols-2">
          <label className="settings-label">昵称<input className="settings-input" name="nickname" required maxLength={40} value={form.nickname} onChange={(event) => setForm({ ...form, nickname: event.target.value })} /></label>
          <label className="settings-label">身份<input className="settings-input bg-page text-ink-2" value="教师" readOnly aria-readonly="true" /></label>
          <label className="settings-label">任教学段<select className="settings-input" value={form.teaching_stage} onChange={(event) => setForm({ ...form, teaching_stage: event.target.value as UserProfile['teaching_stage'], grade: '' })}><option value="">暂未设置</option>{STAGES.map((stage) => <option key={stage.value} value={stage.value}>{stage.label}</option>)}</select></label>
          <label className="settings-label">年级<select disabled={!form.teaching_stage} className="settings-input" value={form.grade} onChange={(event) => setForm({ ...form, grade: event.target.value })}><option value="">暂未设置</option>{form.grade && !gradeOptions?.includes(form.grade) && <option>{form.grade}</option>}{(gradeOptions ?? []).map((grade) => <option key={grade} value={grade}>{gradeLabel(grade)}</option>)}</select></label>
        </fieldset>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5"><span className="text-xs text-ink-2">{dirty ? '有未保存的更改' : '资料已与服务器同步'}</span><div className="flex flex-wrap gap-3"><button type="button" className="settings-button-secondary" disabled={!dirty || busy || uploading} onClick={restore}>恢复已保存资料</button><button type="submit" className="settings-button" disabled={!dirty || busy || uploading}>{busy ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}{uploading ? '正在上传头像…' : '保存资料'}</button></div></div>
      </form>
    </div>
  </div>
}
