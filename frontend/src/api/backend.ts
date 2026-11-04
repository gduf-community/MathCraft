/** 真实后端 API 层：统一封装 fetch、token、字段映射。 */
import type {
  AssembleRecord,
  Difficulty,
  ExamWindow,
  FavoriteGroup,
  KbDocument,
  KnowledgeBase,
  OptionItem,
  PaperModule,
  Question,
  QuestionType,
  StudySpace,
  TeacherProfile,
} from '../types'

import { apiUrl } from './urls'
import { ApiError, getApiToken, request, sessionFetch, ensureSession } from './session'
export { ApiError, request, setApiToken } from './session'

export function fileUrl(path: string): string {
  return path
}

/* ---------------- 认证 ---------------- */

export type AuthRole = 'student' | 'teacher'

export interface ApiUser {
  id: string
  account: string
  role: AuthRole
  identity: string
  display_name: string
  gender?: string | null
  phone?: string | null
  email?: string | null
  user_no?: string | null
  school?: string | null
  avatar_url?: string | null
}

export interface LoginResult {
  access_token: string
  token_type: string
  expires_in: number
  user: ApiUser
}

export interface AuthUser {
  username: string
  role: AuthRole
  displayName: string
  identity: string
  token: string
  userId: string
  avatarUrl?: string
  userNo?: string
  school?: string
  gender?: string
  phone?: string
  email?: string
}

export function mapAuthUser(user: ApiUser, token: string): AuthUser {
  return {
    username: user.account,
    role: user.role,
    displayName: user.display_name,
    identity: user.identity,
    token,
    userId: user.id,
    avatarUrl: user.avatar_url ?? undefined,
    userNo: user.user_no ?? undefined,
    school: user.school ?? undefined,
    gender: user.gender ?? undefined,
    phone: user.phone ?? undefined,
    email: user.email ?? undefined,
  }
}

/* ---------------- 题库 ---------------- */

export interface ApiBankCreator {
  id: string
  display_name: string
}

export interface ApiBank {
  id: string
  name: string
  code: string
  creator: ApiBankCreator | null
  member_count: number
  capacity: number
  source: 'owned' | 'joined'
  quitted: boolean
  my_role: 'owner' | 'admin' | 'member'
  my_admin_level: 'super' | 'normal'
  can_upload_document: boolean
  can_download_document: boolean
  can_delete_document: boolean
  can_manage_members: boolean
  can_edit_bank: boolean
  can_transfer_bank: boolean
  can_delete_bank: boolean
}

export interface ApiBankMember {
  id: string
  user: { id: string; display_name: string; account: string }
  role: 'owner' | 'admin' | 'member'
  is_admin: boolean
  admin_level: 'super' | 'normal' | null
  is_creator: boolean
  is_me: boolean
  joined_at: string
}

export type AdminLevel = 'normal' | 'super'

export async function listBanks(scope: 'owned' | 'joined' | 'all' = 'all'): Promise<ApiBank[]> {
  return request<ApiBank[]>(`/api/banks?scope=${scope}`)
}

export async function createBank(name: string): Promise<ApiBank> {
  return request<ApiBank>('/api/banks', { method: 'POST', body: JSON.stringify({ name }) })
}

export async function getBank(id: string): Promise<ApiBank> {
  return request<ApiBank>(`/api/banks/${id}`)
}

export async function updateBank(
  id: string,
  patch: { name?: string; admin_level?: AdminLevel },
): Promise<ApiBank> {
  return request<ApiBank>(`/api/banks/${id}`, { method: 'PUT', body: JSON.stringify(patch) })
}

export async function deleteBank(id: string): Promise<void> {
  await request<void>(`/api/banks/${id}`, { method: 'DELETE' })
}

export async function joinBank(code: string): Promise<ApiBank> {
  return request<ApiBank>('/api/banks/join', { method: 'POST', body: JSON.stringify({ code }) })
}

export async function quitBank(id: string): Promise<void> {
  await request<void>(`/api/banks/${id}/quit`, { method: 'POST' })
}

export async function listBankMembers(id: string): Promise<ApiBankMember[]> {
  return request<ApiBankMember[]>(`/api/banks/${id}/members`)
}

export async function setBankMemberRole(
  bankId: string,
  userId: string,
  role: 'admin' | 'member',
): Promise<void> {
  await request<void>(`/api/banks/${bankId}/members/${userId}/role`, {
    method: 'PUT',
    body: JSON.stringify({ role }),
  })
}

export async function removeBankMember(bankId: string, userId: string): Promise<void> {
  await request<void>(`/api/banks/${bankId}/members/${userId}`, { method: 'DELETE' })
}

export async function transferBank(bankId: string, targetUserId: string): Promise<void> {
  await request<void>(`/api/banks/${bankId}/transfer`, {
    method: 'POST',
    body: JSON.stringify({ target_user_id: targetUserId }),
  })
}

/* ---------------- 文档 ---------------- */

export interface ApiDocument {
  id: string
  bank_id: string
  name: string
  format: string
  size_bytes: number
  page_count?: number | null
  is_scanned: boolean
  status: 'uploaded' | 'parsing' | 'ocr' | 'chunking' | 'embedding' | 'ready' | 'failed'
  stage?: string | null
  progress: number
  chunk_count: number
  ocr_status?: string | null
  error_message?: string | null
  created_at: string
}

export function formatFileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`
  return `${bytes} B`
}

export function mapDocument(doc: ApiDocument): KbDocument & { api: ApiDocument } {
  return { id: doc.id, kbId: doc.bank_id, name: doc.name, api: doc }
}

export async function listDocuments(bankId: string): Promise<ApiDocument[]> {
  return request<ApiDocument[]>(`/api/banks/${bankId}/documents`)
}

export async function getDocument(bankId: string, docId: string): Promise<ApiDocument> {
  return request<ApiDocument>(`/api/banks/${bankId}/documents/${docId}`)
}

export async function uploadDocument(
  bankId: string,
  file: File,
  onUploadProgress?: (percent: number) => void,
): Promise<{ document_id: string; status: string; stage: string; progress: number }> {
  await ensureSession()
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', apiUrl(`/api/banks/${bankId}/documents`))
    xhr.withCredentials = true
    if (getApiToken()) xhr.setRequestHeader('Authorization', `Bearer ${getApiToken()}`)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onUploadProgress) onUploadProgress(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onerror = () => reject(new ApiError('上传失败，请检查后端服务'))
    xhr.onload = () => {
      try {
        const body = JSON.parse(xhr.responseText || '{}')
        if (xhr.status >= 200 && xhr.status < 300) resolve(body)
        else reject(new ApiError(body?.detail?.message ?? `HTTP ${xhr.status}`, body?.detail?.code))
      } catch {
        reject(new ApiError(`HTTP ${xhr.status}`))
      }
    }
    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}

export async function reprocessDocument(bankId: string, docId: string): Promise<void> {
  await request<void>(`/api/banks/${bankId}/documents/${docId}/reprocess`, { method: 'POST' })
}

export async function deleteDocument(bankId: string, docId: string): Promise<void> {
  await request<void>(`/api/banks/${bankId}/documents/${docId}`, { method: 'DELETE' })
}

export async function downloadDocument(bankId: string, docId: string, name: string): Promise<void> {
  const headers: HeadersInit = {}
  if (getApiToken()) (headers as Record<string, string>).Authorization = `Bearer ${getApiToken()}`
  const resp = await sessionFetch(`/api/banks/${bankId}/documents/${docId}/download`, { headers })
  if (!resp.ok) throw new ApiError('下载失败（HTTP ' + resp.status + '）')
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/* ---------------- 出题与题目 ---------------- */

export interface GenerateBody {
  bank_id: string
  document_id: string
  types: { type: QuestionType; count: number }[]
  difficulty: Difficulty
  scope?: string
  source_mode?: string
  existing_stems?: string[]
}

export interface ApiQuestion {
  id: string
  paper_question_id?: string
  source_question_id?: string | null
  type: QuestionType
  score: number
  difficulty: Difficulty
  stem: string
  options: OptionItem[]
  answer?: string
  analysis?: string
  knowledge_point?: string
  starred?: boolean
  favorite_group_id?: string | null
  doc_name?: string
  bank_id?: string
  document_id?: string
  batch_id?: string
  no?: number
}

export function mapQuestion(q: ApiQuestion): Question {
  return {
    id: q.paper_question_id ?? q.id,
    type: q.type,
    score: q.score,
    difficulty: q.difficulty,
    stem: q.stem,
    options: q.options ?? [],
    answer: q.answer ?? '',
    analysis: q.analysis ?? '',
    knowledgePoint: q.knowledge_point ?? '',
    starred: !!q.starred,
    favGroupId: q.favorite_group_id ?? undefined,
    docName: q.doc_name ?? '',
  }
}

export async function startGeneration(body: GenerateBody): Promise<{ task_id: string }> {
  return request<{ task_id: string }>('/api/generate/start', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export interface GenerateProgress {
  progress: number
  stage: string
  done: boolean
  batch_id: string | null
  questions: ApiQuestion[]
  error: { message?: string; kind?: string; available?: number; requested?: number } | null
}

export async function getGenerationProgress(taskId: string): Promise<GenerateProgress> {
  return request<GenerateProgress>(`/api/generate/progress/${taskId}`)
}

export async function latestBatch(
  bankId?: string,
  documentId?: string,
): Promise<{ batch_id: string | null; questions: ApiQuestion[] }> {
  const params = new URLSearchParams()
  if (bankId) params.set('bank_id', bankId)
  if (documentId) params.set('document_id', documentId)
  return request(`/api/generate/batches/latest?${params.toString()}`)
}

export async function listQuestions(params: {
  batch_id?: string
  bank_id?: string
  document_id?: string
  page?: number
  page_size?: number
}): Promise<{ items: ApiQuestion[]; total: number }> {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') search.set(k, String(v))
  })
  return request(`/api/questions?${search.toString()}`)
}

export async function updateQuestionApi(q: Question): Promise<ApiQuestion> {
  return request<ApiQuestion>(`/api/questions/${q.id}`, {
    method: 'PUT',
    body: JSON.stringify({
      type: q.type,
      score: q.score,
      difficulty: q.difficulty,
      stem: q.stem,
      options: q.options,
      answer: q.answer,
      analysis: q.analysis,
      knowledge_point: q.knowledgePoint,
    }),
  })
}

export async function deleteQuestionApi(id: string): Promise<void> {
  await request<void>(`/api/questions/${id}`, { method: 'DELETE' })
}

export async function batchDeleteQuestions(ids: string[]): Promise<void> {
  await request<void>('/api/questions/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ question_ids: ids }),
  })
}

/* ---------------- 收藏 ---------------- */

export interface ApiFavoriteGroup {
  id: string
  name: string
  is_default: boolean
  count: number
}

export async function listFavoriteGroups(): Promise<ApiFavoriteGroup[]> {
  return request<ApiFavoriteGroup[]>('/api/favorite-groups')
}

export async function createFavoriteGroup(name: string): Promise<ApiFavoriteGroup> {
  return request<ApiFavoriteGroup>('/api/favorite-groups', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export async function renameFavoriteGroup(id: string, name: string): Promise<void> {
  await request<void>(`/api/favorite-groups/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ name }),
  })
}

export async function deleteFavoriteGroup(id: string): Promise<void> {
  await request<void>(`/api/favorite-groups/${id}`, { method: 'DELETE' })
}

export async function listFavorites(groupId?: string): Promise<ApiQuestion[]> {
  const suffix = groupId ? `?group_id=${groupId}` : ''
  return request<ApiQuestion[]>(`/api/favorites${suffix}`)
}

export async function addFavorite(questionId: string, groupId = 'default'): Promise<void> {
  await request<void>('/api/favorites', {
    method: 'POST',
    body: JSON.stringify({ question_id: questionId, group_id: groupId }),
  })
}

export async function moveFavorite(questionId: string, groupId: string): Promise<void> {
  await request<void>(`/api/favorites/${questionId}`, {
    method: 'PUT',
    body: JSON.stringify({ group_id: groupId }),
  })
}

export async function removeFavorite(questionId: string): Promise<void> {
  await request<void>(`/api/favorites/${questionId}`, { method: 'DELETE' })
}

/* ---------------- 学习空间 ---------------- */

export interface ApiSpace {
  id: string
  name: string
  code: string
  creator: ApiBankCreator | null
  member_count: number
  student_count: number
  capacity: number
  status: string
  my_role: 'creator' | 'member'
  can_edit_space: boolean
  can_dissolve_space: boolean
  can_remove_member: boolean
  can_publish_paper: boolean
  can_answer_paper: boolean
  can_leave_space: boolean
  members?: string[]
}

export function mapSpace(s: ApiSpace): StudySpace {
  return {
    id: s.id,
    name: s.name,
    code: s.code,
    memberCount: s.member_count,
    capacity: s.capacity,
    creator: s.creator?.display_name ?? '',
    members: s.members ?? [],
  }
}

export async function listSpaces(): Promise<ApiSpace[]> {
  return request<ApiSpace[]>('/api/spaces')
}

export async function createSpace(name: string, capacity: number): Promise<ApiSpace> {
  return request<ApiSpace>('/api/spaces', { method: 'POST', body: JSON.stringify({ name, capacity }) })
}

export async function getSpace(id: string): Promise<ApiSpace> {
  return request<ApiSpace>(`/api/spaces/${id}`)
}

export async function updateSpace(id: string, name: string): Promise<ApiSpace> {
  return request<ApiSpace>(`/api/spaces/${id}`, { method: 'PUT', body: JSON.stringify({ name }) })
}

export async function dissolveSpace(id: string): Promise<void> {
  await request<void>(`/api/spaces/${id}`, { method: 'DELETE' })
}

export async function joinSpace(code: string): Promise<ApiSpace> {
  return request<ApiSpace>('/api/spaces/join', { method: 'POST', body: JSON.stringify({ code }) })
}

export async function leaveSpace(id: string): Promise<void> {
  await request<void>(`/api/spaces/${id}/leave`, { method: 'POST' })
}

export async function listSpaceMembers(id: string): Promise<{ id: string; user: ApiBankCreator; role: string; is_creator: boolean; is_me: boolean }[]> {
  return request(`/api/spaces/${id}/members`)
}

export async function removeSpaceMember(spaceId: string, userId: string): Promise<void> {
  await request<void>(`/api/spaces/${spaceId}/members/${userId}`, { method: 'DELETE' })
}

/** 空间内发布的试卷（学生作答入口；与组卷记录严格隔离） */
export interface ApiSpacePaper {
  id: string
  name: string
  created_at: string
  question_count: number
  total_score: number
  status: string
  exam_window: { start: string; end: string } | null
  stopped: boolean
  submitted_count: number
  student_count: number
  answered: boolean
  allow_review: boolean
  allow_retake: boolean
  last_urge_at?: string | null
}

export async function listSpacePapers(spaceId: string): Promise<ApiSpacePaper[]> {
  return request<ApiSpacePaper[]>(`/api/spaces/${spaceId}/papers`)
}

/* ---------------- 催交 ---------------- */

export interface ApiUrge {
  id: string
  paper_id: string
  paper_name: string
  space_id: string
  space_name: string
  teacher_name: string
  created_at: string
  exam_end: string | null
}

export async function urgePaper(paperId: string, spaceId: string): Promise<void> {
  await request<void>(`/api/papers/${paperId}/publications/${spaceId}/urge`, { method: 'POST' })
}

export async function listMyUrges(): Promise<{ unread_count: number; items: ApiUrge[] }> {
  return request<{ unread_count: number; items: ApiUrge[] }>('/api/urges')
}

export async function clearUrgeBadge(): Promise<void> {
  await request<void>('/api/urges/clear', { method: 'POST' })
}

export async function markUrgeRead(urgeId: string): Promise<void> {
  await request<void>(`/api/urges/${urgeId}/read`, { method: 'POST' })
}

export async function deleteUrge(urgeId: string): Promise<void> {
  await request<void>(`/api/urges/${urgeId}`, { method: 'DELETE' })
}

/* ---------------- 组卷 ---------------- */

export interface ApiPaperSpace {
  space_id: string
  name: string
  stopped: boolean
  published_at: string
}

export interface ApiPaper {
  id: string
  name: string
  owner_id: string
  created_at: string
  updated_at: string
  question_count: number
  total_score: number
  status: 'draft' | 'published'
  saved_to_records: boolean
  allow_review: boolean
  allow_retake: boolean
  exam_window: { start: string; end: string } | null
  spaces: ApiPaperSpace[]
  submitted_count: number
  student_count: number
  answered: boolean
  modules_order: PaperModule[]
  questions?: ApiQuestion[]
}

export function formatDateTime(value?: string | null): string {
  if (!value) return ''
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

export function toLocalInput(value?: string | null): string {
  if (!value) return ''
  const d = new Date(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function toIso(value?: string | null): string | null {
  if (!value) return null
  return new Date(value).toISOString()
}

export function mapPaper(p: ApiPaper): AssembleRecord {
  return {
    id: p.id,
    name: p.name,
    createdAt: formatDateTime(p.created_at),
    questionCount: p.question_count,
    totalScore: p.total_score,
    spaces: p.spaces.map((s) => s.name),
    published: p.status === 'published',
    questions: p.questions?.map(mapQuestion),
    examWindow: p.exam_window
      ? { start: toLocalInput(p.exam_window.start), end: toLocalInput(p.exam_window.end) }
      : null,
    submittedCount: p.submitted_count,
    savedToRecords: p.saved_to_records,
    allowReview: p.allow_review,
    allowRetake: p.allow_retake,
    modulesOrder: p.modules_order,
    answered: p.answered,
    stopped: p.spaces.some((s) => s.stopped),
  }
}

export interface PaperCreatePayload {
  name: string
  questions: string[]
  space_ids: string[]
  save_to_records: boolean
  is_published: boolean
  exam_window?: ExamWindow | null
  allow_review?: boolean
  allow_retake?: boolean
}

function paperBody(payload: PaperCreatePayload) {
  return {
    name: payload.name,
    questions: payload.questions,
    space_ids: payload.space_ids,
    save_to_records: payload.save_to_records,
    is_published: payload.is_published,
    allow_review: payload.allow_review,
    allow_retake: payload.allow_retake,
    exam_start: toIso(payload.exam_window?.start),
    exam_end: toIso(payload.exam_window?.end),
  }
}

export async function listPapers(params: {
  include_drafts?: boolean
  saved?: boolean
  space_id?: string
} = {}): Promise<ApiPaper[]> {
  const search = new URLSearchParams()
  if (params.include_drafts !== undefined) search.set('include_drafts', String(params.include_drafts))
  if (params.saved !== undefined) search.set('saved', String(params.saved))
  if (params.space_id) search.set('space_id', params.space_id)
  return request<ApiPaper[]>(`/api/papers?${search.toString()}`)
}

export async function createPaperApi(payload: PaperCreatePayload): Promise<ApiPaper> {
  return request<ApiPaper>('/api/papers', { method: 'POST', body: JSON.stringify(paperBody(payload)) })
}

export async function getPaperApi(id: string): Promise<ApiPaper> {
  return request<ApiPaper>(`/api/papers/${id}`)
}

export async function updatePaperApi(
  id: string,
  payload: Partial<PaperCreatePayload> & { is_published?: boolean; modules_order?: PaperModule[] },
): Promise<ApiPaper> {
  const body: Record<string, unknown> = {}
  if (payload.name !== undefined) body.name = payload.name
  if (payload.questions !== undefined) body.questions = payload.questions
  if (payload.space_ids !== undefined) body.space_ids = payload.space_ids
  if (payload.is_published !== undefined) body.is_published = payload.is_published
  if (payload.modules_order !== undefined) body.modules_order = payload.modules_order
  if (payload.allow_review !== undefined) body.allow_review = payload.allow_review
  if (payload.allow_retake !== undefined) body.allow_retake = payload.allow_retake
  if (payload.exam_window !== undefined) {
    body.exam_start = toIso(payload.exam_window?.start)
    body.exam_end = toIso(payload.exam_window?.end)
  }
  return request<ApiPaper>(`/api/papers/${id}`, { method: 'PUT', body: JSON.stringify(body) })
}

export async function deletePaperApi(id: string, mode: 'record' | 'paper' = 'record'): Promise<void> {
  // mode=record：仅从组卷记录移除（已发布卷保留在空间）；mode=paper：整卷删除
  await request<void>(`/api/papers/${id}?mode=${mode}`, { method: 'DELETE' })
}

export async function batchDeletePapers(ids: string[]): Promise<void> {
  await request<void>('/api/papers/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ paper_ids: ids }),
  })
}

export async function removePaperQuestions(paperId: string, paperQuestionIds: string[]): Promise<ApiPaper> {
  return request<ApiPaper>(`/api/papers/${paperId}/questions/remove`, {
    method: 'POST',
    body: JSON.stringify({ paper_question_ids: paperQuestionIds }),
  })
}

export async function publishPaperApi(
  id: string,
  spaceIds: string[],
  examWindow?: ExamWindow | null,
): Promise<ApiPaper> {
  return request<ApiPaper>(`/api/papers/${id}/publish`, {
    method: 'POST',
    body: JSON.stringify({
      space_ids: spaceIds,
      exam_start: toIso(examWindow?.start),
      exam_end: toIso(examWindow?.end),
    }),
  })
}

export async function stopPublication(paperId: string, spaceId: string): Promise<void> {
  await request<void>(`/api/papers/${paperId}/publications/${spaceId}/stop`, { method: 'POST' })
}

export async function resumePublication(paperId: string, spaceId: string): Promise<void> {
  await request<void>(`/api/papers/${paperId}/publications/${spaceId}/resume`, { method: 'POST' })
}

export async function deletePublication(paperId: string, spaceId: string): Promise<void> {
  await request<void>(`/api/papers/${paperId}/publications/${spaceId}`, { method: 'DELETE' })
}

export interface ApiStatistics {
  paper_id: string
  space_id: string
  student_count: number
  submitted_count: number
  questions: {
    paper_question_id: string
    no: number
    type: QuestionType
    average_score: number
    correct_rate: number
    option_counts?: { label: string; count: number }[]
  }[]
}

export async function getStatistics(paperId: string, spaceId: string): Promise<ApiStatistics> {
  return request<ApiStatistics>(`/api/papers/${paperId}/statistics?space_id=${spaceId}`)
}

/* ---------------- 作答 ---------------- */

export interface ApiAttempt {
  id: string
  status: 'answering' | 'submitted'
  score: number | null
  total_score: number
  started_at: string
  submitted_at: string | null
}

export interface ApiAttemptPayload {
  paper: { id: string; name: string; total_score: number; allow_review: boolean; allow_retake: boolean; exam_window: { start: string; end: string } | null; stopped: boolean }
  space: { id: string; name: string } | null
  questions: ApiQuestion[]
  attempt: ApiAttempt | null
  answers: { paper_question_id: string; choices: string[]; text: string; score: number; is_correct: boolean; grading_note?: string | null }[]
}

export async function getAttempt(paperId: string, spaceId?: string | null): Promise<ApiAttemptPayload> {
  const suffix = spaceId ? `?space_id=${spaceId}` : ''
  return request<ApiAttemptPayload>(`/api/papers/${paperId}/attempt${suffix}`)
}

export async function createAttempt(paperId: string, spaceId?: string | null): Promise<ApiAttemptPayload> {
  return request<ApiAttemptPayload>(`/api/papers/${paperId}/attempts`, {
    method: 'POST',
    body: JSON.stringify({ space_id: spaceId ?? null }),
  })
}

export async function submitAttempt(
  attemptId: string,
  answers: { paper_question_id: string; choices: string[]; text: string }[],
): Promise<{ attempt_id: string; score: number; total_score: number; detail: { paper_question_id: string; score: number; is_correct: boolean; answer: string; analysis: string }[] }> {
  return request(`/api/attempts/${attemptId}/submit`, {
    method: 'POST',
    body: JSON.stringify({ answers }),
  })
}

export async function reviewAttempt(attemptId: string): Promise<ApiAttemptPayload> {
  return request<ApiAttemptPayload>(`/api/attempts/${attemptId}/review`)
}

/* ---------------- 个人资料与模型配置 ---------------- */

export async function updateProfile(patch: Partial<TeacherProfile> & { school?: string }): Promise<ApiUser> {
  return request<ApiUser>('/api/users/me', {
    method: 'PUT',
    body: JSON.stringify({
      display_name: patch.name,
      gender: patch.gender,
      phone: patch.phone,
      school: patch.school,
    }),
  })
}

export interface ModelSettings {
  deepseek_model: string
  deepseek_model_id: string
  deepseek_key_configured: boolean
  deepseek_key_masked: string | null
  mineru_token_configured: boolean
  mineru_token_masked: string | null
  mineru_using_default: boolean
  mineru_limits: { max_file_mb: number; max_pages: number }
  embedding_model: string
  rerank_model: string
  embedding_configurable: boolean
  rerank_configurable: boolean
}

export async function getModelSettings(): Promise<ModelSettings> {
  return request<ModelSettings>('/api/users/me/model-settings')
}

export async function saveModelSettings(payload: {
  deepseek_api_key?: string
  mineru_token?: string
}): Promise<void> {
  await request<void>('/api/users/me/model-settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function testDeepSeek(): Promise<void> {
  await request<void>('/api/users/me/model-settings/test-deepseek', { method: 'POST' })
}

export async function testMinerU(): Promise<void> {
  await request<void>('/api/users/me/model-settings/test-mineru', { method: 'POST' })
}

/* ---------------- 对话出题 ---------------- */

export interface ChatSession {
  session_id: string
  bank_id: string
  document_id: string
  welcome?: string
}

export async function createChatSession(bankId: string, documentId: string): Promise<ChatSession> {
  return request<ChatSession>('/api/chat/sessions', {
    method: 'POST',
    body: JSON.stringify({ bank_id: bankId, document_id: documentId }),
  })
}

export async function getChatSession(sessionId: string): Promise<{ messages: { role: 'user' | 'assistant'; text: string }[] }> {
  return request(`/api/chat/sessions/${sessionId}`)
}

export async function sendChatMessage(
  sessionId: string,
  message: string,
  existingStems: string[],
): Promise<{ reply: string; questions: ApiQuestion[]; done: boolean; batch_id: string | null; slot_state: Record<string, unknown> }> {
  return request(`/api/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ message, existing_stems: existingStems }),
  })
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await request<void>(`/api/chat/sessions/${sessionId}`, { method: 'DELETE' })
}

/* ---------------- 通用映射 ---------------- */

export function mapBankToKnowledgeBase(bank: ApiBank): KnowledgeBase {
  return { id: bank.id, name: bank.name }
}

export function mapFavoriteGroup(g: ApiFavoriteGroup): FavoriteGroup {
  return { id: g.id, name: g.name }
}
