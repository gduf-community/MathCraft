import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { settingsRequest } from '../api/settingsHttp'
import type { UserProfile } from '../types/profile'

interface ProfileState {
  profile: UserProfile | null
  error: string
  loading: boolean
  refresh: () => Promise<void>
  updateProfile: (value: UserProfile) => void
}
const ProfileContext = createContext<ProfileState | null>(null)

export function ProfileProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try { setProfile(await settingsRequest<UserProfile>('/api/user-profile')) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '个人资料读取失败，请重试') }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])
  return <ProfileContext.Provider value={{ profile, error, loading, refresh, updateProfile: setProfile }}>{children}</ProfileContext.Provider>
}
export function useProfile(): ProfileState {
  const value = useContext(ProfileContext)
  if (!value) throw new Error('useProfile must be used within ProfileProvider')
  return value
}
