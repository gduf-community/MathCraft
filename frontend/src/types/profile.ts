/** 单租户教师资料，与 /api/user-profile 契约一致。 */
export interface UserProfile {
  nickname: string
  role: 'teacher'
  teaching_stage: '' | 'primary' | 'junior' | 'senior'
  grade: string
  avatar_url: string | null
}
export type ProfileUpdate = Pick<UserProfile, 'nickname' | 'teaching_stage' | 'grade'>
