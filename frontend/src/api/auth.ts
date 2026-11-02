/**
 * 登录认证 API 层。
 * 当前为演示实现：本地校验两个演示账号，不发起网络请求。
 * 接入真实后端时，替换 login / fetchAuthUser 的实现为
 * fetch(AUTH_ENDPOINTS.login) 与 fetch(AUTH_ENDPOINTS.user) 即可，
 * 页面与状态层（AuthContext）不需要改动。
 */

/** 用户角色：学生 / 教师 */
export type AuthRole = 'student' | 'teacher'

/** 登录成功后的用户信息（与后端用户系统对齐的最小字段集） */
export interface AuthUser {
  /** 登录账号 */
  username: string
  role: AuthRole
  /** 界面显示名 */
  displayName: string
  /** 身份徽章文案 */
  identity: string
  /** 后端签发的会话令牌（演示态为本地占位值） */
  token: string
}

/** 后端认证端点预留 */
export const AUTH_ENDPOINTS = {
  /** POST { account, password, role } → { token, username, role, displayName, identity } */
  login: '/api/auth/login',
  /** GET（Authorization: Bearer token）→ 用户信息 */
  user: '/api/auth/user',
} as const

/** 演示账号：学生与教师，密码一致 */
const DEMO_PASSWORD = '123123'
const DEMO_ACCOUNTS: Record<AuthRole, { username: string; displayName: string; identity: string }> = {
  student: { username: 'student', displayName: '小明', identity: '学生' },
  teacher: { username: 'teacher', displayName: '张老师', identity: '教师' },
}

/**
 * 登录。演示实现按身份校验演示账号与密码；
 * 真实后端接入时改为：
 *   const resp = await fetch(AUTH_ENDPOINTS.login, {
 *     method: 'POST',
 *     headers: { 'Content-Type': 'application/json' },
 *     body: JSON.stringify({ account, password, role }),
 *   })
 */
export async function login(account: string, password: string, role: AuthRole): Promise<AuthUser> {
  const trimmed = account.trim().toLowerCase()
  // 模拟网络延迟，保证登录态过渡动画可感知
  await new Promise((resolve) => setTimeout(resolve, 450))
  const demo = DEMO_ACCOUNTS[role]
  if (trimmed !== demo.username) {
    throw new Error(role === 'student' ? '演示学生账号为 student' : '演示教师账号为 teacher')
  }
  if (password !== DEMO_PASSWORD) {
    throw new Error('密码不正确，演示密码为 123123')
  }
  return {
    username: demo.username,
    role,
    displayName: demo.displayName,
    identity: demo.identity,
    token: `demo-token-${role}-${Date.now()}`,
  }
}

/**
 * 按会话令牌获取用户信息（用于刷新页面后恢复登录态的校验）。
 * 演示实现直接信任本地存储；真实后端接入时改为 fetch(AUTH_ENDPOINTS.user)。
 */
export async function fetchAuthUser(token: string): Promise<AuthUser | null> {
  if (!token.startsWith('demo-token-')) return null
  const role: AuthRole = token.includes('-student-') ? 'student' : 'teacher'
  const demo = DEMO_ACCOUNTS[role]
  return {
    username: demo.username,
    role,
    displayName: demo.displayName,
    identity: demo.identity,
    token,
  }
}
