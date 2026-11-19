import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import * as api from '../api/backend'
import * as banksApi from '../api/banks'
import { getSessionGeneration } from '../api/session'
import type {
  AssembleRecord,
  ChatConfirm,
  ChatMessage,
  ChatMode,
  Difficulty,
  ExamWindow,
  FavoriteGroup,
  KbDocument,
  KnowledgeBase,
  PaperModule,
  Question,
  QuestionType,
  StudySpace,
  TeacherProfile,
} from '../types'
import { orderQuestionsByModules } from '../lib/order'
import { CHAT_MODE_LABELS } from '../types'

import { useAuth } from './AuthContext'
import { useGenerationTask } from './useGenerationTask'
import { useToast } from './ToastContext'
import type { ToastMessage, ToastVariant } from './ToastContext'
import type { AuthRole, AuthUser } from '../api/auth'

const isChatMode = (value: string): value is ChatMode => value in CHAT_MODE_LABELS
const QUESTION_DELETE_BATCH_SIZE = 200

interface ChatTurn {
  requestId: string
  sessionId: string
  bankId: string
  docId: string
}

export type TabKey = 'generate' | 'preview' | 'bank' | 'records' | 'fav' | 'space' | 'me'

/** 历史会话侧边栏列表项（来自后端，按账号隔离） */
export interface ChatSessionSummary {
  id: string
  title: string
  bankId: string
  docId: string
  documentName?: string | null
  lastMessageAt: string | null
}

function buildProfile(user: AuthUser | null): TeacherProfile {
  return {
    name: user?.displayName ?? '',
    avatar: user?.avatarUrl ?? '',
    gender: user?.gender === '男' || user?.gender === '女' ? user.gender : '',
    phone: user?.phone ?? '',
    email: user?.email ?? '',
    teacherId: user?.username ?? '',
    school: user?.school ?? '',
    identity: user?.identity ?? '',
  }
}

function profileFromApi(user: api.ApiUser, token: string): TeacherProfile {
  const mapped = api.mapAuthUser(user, token)
  return buildProfile(mapped)
}

function dedupeQuestions(prev: Question[], next: Question[]): Question[] {
  const seen = new Set(prev.map((q) => q.id))
  return [...prev, ...next.filter((q) => !seen.has(q.id))]
}

interface AppState {
  activeTab: TabKey
  setActiveTab: (t: TabKey) => void
  navCollapsed: boolean
  toggleNav: () => void
  historyCollapsed: boolean
  toggleHistory: () => void

  kbs: KnowledgeBase[]
  docs: KbDocument[]
  spaces: StudySpace[]
  selectedKbId: string
  selectedDocId: string
  selectKb: (id: string) => void
  selectDoc: (id: string) => void
  /** 重新拉取题库列表（题库新建/加入/退出后侧边栏实时同步） */
  refreshKbs: () => Promise<void>
  /** 删除受理后立即清理选中项与缓存，阻止旧请求重新写入。 */
  invalidateDocument: (bankId: string, documentId: string) => void

  /** 个人 API 配置（脱敏）；未配置 DeepSeek Key 时出题被拦截 */
  modelSettings: api.ModelSettings | null
  refreshModelSettings: () => Promise<void>
  /** 未配置 API 时的引导弹窗 */
  apiConfigOpen: boolean
  closeApiConfigModal: () => void

  generationRecoveryError: string | null
  resetGenerationRecovery: () => void
  retryGenerationCleanup: () => Promise<void>
  generating: boolean
  generationClearing: boolean
  questionsClearing: boolean
  questions: Question[]
  favorites: Question[]
  favGroups: FavoriteGroup[]
  addFavGroup: () => Promise<FavoriteGroup>
  renameFavGroup: (id: string, name: string) => void
  removeFavGroup: (id: string) => void
  addToFavorites: (q: Question, groupId: string) => void
  unfavoriteQuestion: (questionId: string) => void
  setFavoriteGroup: (questionId: string, groupId: string) => void
  profile: TeacherProfile
  updateProfile: (patch: Partial<TeacherProfile>) => Promise<void>

  selectedIds: string[]
  toggleSelect: (id: string) => void
  selectAll: (ids: string[]) => void
  clearSelection: () => void
  typeFilter: QuestionType | 'all'
  setTypeFilter: (t: QuestionType | 'all') => void
  diffFilter: Difficulty | 'all'
  setDiffFilter: (d: Difficulty | 'all') => void
  updateQuestion: (q: Question) => Promise<void>
  deleteQuestion: (id: string) => Promise<void>
  toggleStar: (id: string) => Promise<void>

  records: AssembleRecord[]
  publishPaper: (
    modules: PaperModule[],
    spaceIds: string[],
    saveRecord: boolean,
    name?: string,
    published?: boolean,
    questions?: Question[],
    examWindow?: ExamWindow | null,
    allowReview?: boolean,
    allowRetake?: boolean,
  ) => Promise<boolean>
  /** 一键清空（题目预览）：只清空题目内容与勾选，不影响对话记录和当前会话 */
  clearQuestions: () => Promise<void>
  deleteSelected: () => Promise<void>
  uploadDocument: (file: File) => Promise<void>
  deleteRecord: (id: string, opts?: { withPaper?: boolean }) => Promise<boolean>
  deleteRecords: (ids: string[]) => Promise<boolean>
  deleteRecordQuestions: (recordId: string, ids: string[]) => Promise<boolean>
  setRecordClosed: (id: string, closed: boolean) => Promise<boolean>
  refreshRecord: (id: string) => Promise<void>
  publishRecords: (ids: string[]) => void
  role: AuthRole | null
  createSpace: (name: string, capacity: number) => Promise<StudySpace>
  updateRecord: (record: AssembleRecord) => void
  joinSpaceByCode: (code: string) => Promise<StudySpace | null>
  leaveSpace: (id: string) => void
  dissolveSpace: (id: string) => void
  removeSpaceMember: (spaceId: string, name: string) => void
  renameSpace: (spaceId: string, newName: string) => void
  markRecordAnswered: (recordId: string, answered: boolean) => void
  openPaperId: string | null
  requestOpenPaper: (recordId: string) => void
  clearOpenPaper: () => void

  /** 催交：学生未读角标、通知列表、清除红点 */
  urgeUnread: number
  urgeItems: api.ApiUrge[]
  clearUrgeBadge: () => void
  /** 单条催交标记已读（点击立即查看时消除该条红点） */
  markUrgeRead: (urgeId: string) => void
  /** 删除单条催交通知 */
  deleteUrge: (urgeId: string) => void

  /** 题库通知：文档入库完成/失败，全员可见，红点 + 列表 */
  bankNotifUnread: number
  bankNotifItems: api.ApiNotification[]
  clearBankNotifs: () => void
  /** 删除单条题库通知 */
  deleteBankNotif: (id: string) => void
  /** 通知「立即查看」：跳转到学习空间中该试卷的作答标签页 */
  pendingSpacePaper: { spaceId: string; paperId: string } | null
  requestOpenSpacePaper: (spaceId: string, paperId: string) => void
  clearPendingSpacePaper: () => void

  messages: ChatMessage[]
  botThinking: boolean
  /** 历史会话消息加载中：切换会话时为真，期间不渲染欢迎态避免布局弹跳 */
  sessionLoading: boolean
  inputDraft: string
  setInputDraft: (v: string) => void
  /** 历史会话列表（当前账号，后端持久化） */
  sessions: ChatSessionSummary[]
  /** 当前激活的会话 id；null 表示新对话（欢迎态） */
  activeSessionId: string | null
  /** 打开历史会话：恢复题库文档选择与消息，可继续对话 */
  openSession: (session: ChatSessionSummary) => Promise<void>
  /** 新建对话：清空当前对话视图回到欢迎态（不改历史记录） */
  startNewChat: () => void
  /** 删除一条历史会话（同步后端）；若删除的是当前会话则回到欢迎态 */
  removeSession: (sessionId: string) => Promise<void>
  /** 分段控制器当前模式：用户显式选择，优先级最高 */
  mode: ChatMode
  setMode: (m: ChatMode) => void
  /** 后端已确认生效的会话模式 */
  sessionMode: ChatMode
  /** 分段控制器是否显示：新会话、模式不一致、切换中显示，AI 确认后隐藏 */
  modeVisible: boolean
  /** 最近一次意图识别建议的模式（仅提示，不自动切换） */
  modeSuggested: ChatMode | null
  /** 数据管理高危操作待确认载荷 */
  pendingConfirm: ChatConfirm | null
  confirmBusy: boolean
  confirmOperation: (accepted: boolean) => Promise<void>
  /** 待发送的图片（data URL），随下一条消息一起发出 */
  chatImages: string[]
  addChatImages: (files: File[]) => void
  removeChatImage: (index: number) => void
  sendChat: (text: string, images?: string[], opts?: { switchOnly?: boolean; mode?: ChatMode }) => Promise<void>
  /** 中止当前对话请求（服务端仍会跑完，前端不再等结果） */
  pauseChat: () => void
  chatPauseStatus: 'pending' | 'failed' | null
  /** 回退到这条消息重新发送 */
  retryChat: (messageId: string) => void
  /** 把这条消息放回输入框继续编辑 */
  editChat: (messageId: string) => void
  /** 对话生成的实时阶段，等待时显示 */
  chatProgress: { percent: number; stage: string } | null
  /** 本次对话开始时间，用于显示已等待时长 */
  chatStartedAt: number | null

  toast: ToastMessage | null
  showToast: (text: string, variant?: ToastVariant) => void
  dismissToast: () => void
}

const AppContext = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const user = useAuth().user
  const { toast, showToast: showSharedToast, dismissToast } = useToast()
  const [activeTab, setActiveTabState] = useState<TabKey>('generate')
  const activeTabRef = useRef<TabKey>('generate')
  const [navCollapsed, setNavCollapsed] = useState(false)
  const [historyCollapsed, setHistoryCollapsed] = useState(false)

  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [docs, setDocs] = useState<KbDocument[]>([])
  const [spaces, setSpaces] = useState<StudySpace[]>([])
  const [selectedKbId, setSelectedKbId] = useState('')
  const [selectedDocId, setSelectedDocId] = useState('')

  const [questions, setQuestions] = useState<Question[]>([])
  const [favorites, setFavorites] = useState<Question[]>([])
  const [favGroups, setFavGroups] = useState<FavoriteGroup[]>([])
  const [profile, setProfile] = useState<TeacherProfile>(() => buildProfile(user))
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [typeFilter, setTypeFilter] = useState<QuestionType | 'all'>('all')
  const [diffFilter, setDiffFilter] = useState<Difficulty | 'all'>('all')

  const [records, setRecords] = useState<AssembleRecord[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [sessionLoading, setSessionLoading] = useState(false)
  const sessionLoadingRef = useRef(false)
  const [questionsClearing, setQuestionsClearing] = useState(false)
  const clearQuestionsFlight = useRef<Promise<void> | null>(null)
  const previewVersionRef = useRef(0)
  const sessionsRequestVersion = useRef(0)
  const [chatProgress, setChatProgress] = useState<{ percent: number; stage: string } | null>(null)
  const [chatStartedAt, setChatStartedAt] = useState<number | null>(null)
  const [botThinking, setBotThinking] = useState(false)
  const [chatPauseStatus, setChatPauseStatus] = useState<'pending' | 'failed' | null>(null)
  const [inputDraft, setInputDraft] = useState('')
  const [chatImages, setChatImages] = useState<string[]>([])
  const [mode, setModeState] = useState<ChatMode>('generate')
  const [sessionMode, setSessionMode] = useState<ChatMode>('generate')
  const [modeVisible, setModeVisible] = useState(true)
  const [modeSuggested, setModeSuggested] = useState<ChatMode | null>(null)
  const [pendingConfirm, setPendingConfirmState] = useState<ChatConfirm | null>(null)
  const [confirmBusy, setConfirmBusy] = useState(false)
  const [openPaperId, setOpenPaperId] = useState<string | null>(null)
  const [urgeUnread, setUrgeUnread] = useState(0)
  const [urgeItems, setUrgeItems] = useState<api.ApiUrge[]>([])
  const [bankNotifUnread, setBankNotifUnread] = useState(0)
  const [bankNotifItems, setBankNotifItems] = useState<api.ApiNotification[]>([])
  const [pendingSpacePaper, setPendingSpacePaper] = useState<{ spaceId: string; paperId: string } | null>(null)
  // 个人 API 配置：登录后读取一次；未配置 DeepSeek Key 时弹出引导并拦截出题
  const [modelSettings, setModelSettings] = useState<api.ModelSettings | null>(null)
  const [apiConfigOpen, setApiConfigOpen] = useState(false)
  const apiConfigPromptedRef = useRef(false)

  const activeBatchRef = useRef<string | null>(null)
  const chatSessionRef = useRef<{ id: string; bankId: string; docId: string } | null>(null)
  const chatAbortRef = useRef<AbortController | null>(null)
  const chatBusyRef = useRef(false)
  const activeChatTurn = useRef<ChatTurn | null>(null)
  const pendingChatPause = useRef<ChatTurn | null>(null)
  const chatPauseController = useRef<AbortController | null>(null)
  const chatPauseKey = user ? `mathcraft:chat-pause:${user.userId}` : null
  const chatVersionRef = useRef(0)
  const messageIdRef = useRef(0)
  const imageVersionRef = useRef(0)
  const chatImagesRef = useRef<string[]>([])
  const pendingConfirmRef = useRef<ChatConfirm | null>(null)
  const confirmRequestRef = useRef<AbortController | null>(null)
  const selectedDocRef = useRef('')
  const setPendingConfirm = useCallback((confirm: ChatConfirm | null) => {
    pendingConfirmRef.current = confirm
    setPendingConfirmState(confirm)
  }, [])
  const chatPollRef = useRef<number | null>(null)
  const providerSession = useRef(getSessionGeneration())
  const bankRequestVersion = useRef(0)
  const documentRequestVersion = useRef(0)
  const favoritesRequestVersion = useRef(0)
  const recordsRequestVersion = useRef(0)
  const pendingDocumentSelection = useRef<{
    bankId: string
    documentId: string
    chatVersion: number
  } | null>(null)
  const mounted = useRef(true)
  const sessionIsCurrent = useCallback(
    () => mounted.current && providerSession.current === getSessionGeneration(),
    [],
  )

  const refreshModelSettings = useCallback(async () => {
    const fresh = await api.getModelSettings()
    if (!sessionIsCurrent()) return
    setModelSettings(fresh)
    const missing = !fresh.deepseek_key_configured || !fresh.mineru_token_configured
    if (missing && !apiConfigPromptedRef.current) {
      apiConfigPromptedRef.current = true
      setApiConfigOpen(true)
    }
  }, [sessionIsCurrent])
  const closeApiConfigModal = useCallback(() => setApiConfigOpen(false), [])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (chatPollRef.current !== null) window.clearInterval(chatPollRef.current)
      chatAbortRef.current?.abort()
      chatPauseController.current?.abort()
      chatPauseController.current = null
      confirmRequestRef.current?.abort()
    }
  }, [])

  const showToast = useCallback((text: string, variant: ToastVariant = 'info') => {
    if (!sessionIsCurrent()) return
    showSharedToast(text, variant)
  }, [sessionIsCurrent, showSharedToast])

  const removeClearedFavorites = useCallback((ids: string[]) => {
    favoritesRequestVersion.current += 1
    setFavorites(previous => previous.filter(question => !ids.includes(question.id)))
  }, [])
  const {
    generating, generationClearing, isClearing, generationRecoveryError, resetGenerationRecovery,
    clear: clearRecoveredGeneration,
  } = useGenerationTask(user?.userId, sessionIsCurrent, removeClearedFavorites)
  const retryGenerationCleanup = useCallback(
    () => clearRecoveredGeneration([], null),
    [clearRecoveredGeneration],
  )

  const setActiveTab = useCallback((tab: TabKey): boolean => {
    if (tab === activeTabRef.current) return true
    activeTabRef.current = tab
    setActiveTabState(tab)
    return true
  }, [])

  // 同步失效会话回调，防止清空、切库或切文档后的旧结果回填。
  const resetChat = useCallback(() => {
    if (pendingChatPause.current) return
    chatVersionRef.current += 1
    previewVersionRef.current += 1
    sessionLoadingRef.current = false
    pendingDocumentSelection.current = null
    imageVersionRef.current += 1
    chatAbortRef.current?.abort()
    confirmRequestRef.current?.abort()
    chatAbortRef.current = null
    activeChatTurn.current = null
    confirmRequestRef.current = null
    chatSessionRef.current = null
    chatBusyRef.current = false
    if (chatPollRef.current !== null) window.clearInterval(chatPollRef.current)
    chatPollRef.current = null
    setBotThinking(false)
    setSessionLoading(false)
    setConfirmBusy(false)
    setChatProgress(null)
    setChatStartedAt(null)
    setMessages([])
    setInputDraft('')
    chatImagesRef.current = []
    setChatImages([])
    setModeState('generate')
    setSessionMode('generate')
    setModeVisible(true)
    setModeSuggested(null)
    setPendingConfirm(null)
    setActiveSessionId(null)
  }, [setPendingConfirm])

  /** 按请求版本刷新历史会话列表，失败保留已有记录。 */
  const loadSessions = useCallback(async () => {
    if (!sessionIsCurrent()) return
    const version = ++sessionsRequestVersion.current
    try {
      const rows = await api.listChatSessions()
      if (!sessionIsCurrent() || version !== sessionsRequestVersion.current) return
      setSessions(rows.map((row) => ({
        id: row.session_id,
        title: row.title,
        bankId: row.bank_id,
        docId: row.document_id,
        documentName: row.document_name,
        lastMessageAt: row.last_message_at ?? null,
      })))
      // 列表刷新后校验当前激活会话是否仍存在（可能已被其他入口删除）
      setActiveSessionId((current) => current && rows.some((row) => row.session_id === current) ? current : null)
    } catch (error: unknown) {
      if (sessionIsCurrent() && version === sessionsRequestVersion.current) {
        showToast(error instanceof Error ? error.message : '历史会话列表加载失败，请重试', 'error')
      }
    }
  }, [sessionIsCurrent, showToast])

  const loadFavorites = useCallback(async (isActive = sessionIsCurrent) => {
    if (!sessionIsCurrent() || !isActive()) return
    const version = ++favoritesRequestVersion.current
    const [apiFavs, apiGroups] = await Promise.all([api.listFavorites(), api.listFavoriteGroups()])
    if (!sessionIsCurrent() || !isActive() || version !== favoritesRequestVersion.current) return
    setFavorites(apiFavs.map(api.mapQuestion))
    setFavGroups(apiGroups.map((g) => ({ id: g.id, name: g.name, isDefault: g.is_default })))
  }, [sessionIsCurrent])

  const loadRecords = useCallback(async (isActive = sessionIsCurrent) => {
    if (!sessionIsCurrent() || !isActive()) return
    const version = ++recordsRequestVersion.current
    const rows = await api.listPapers()
    if (!sessionIsCurrent() || !isActive() || version !== recordsRequestVersion.current) return
    const details = await Promise.all(
      rows.map(async (p) => {
        try {
          return await api.getPaperApi(p.id, p.deleted)
        } catch (error) {
          console.error('加载试卷详情失败', error)
          return p
        }
      }),
    )
    if (!sessionIsCurrent() || !isActive() || version !== recordsRequestVersion.current) return
    setRecords(details.map(api.mapPaper))
    setOpenPaperId(current => current && !rows.some(paper => paper.id === current) ? null : current)
  }, [sessionIsCurrent])

  const refreshSpaces = useCallback(async () => {
    if (!sessionIsCurrent()) return
    const rows = await api.listSpaces()
    if (!sessionIsCurrent()) return
    setSpaces(rows.map(api.mapSpace))
  }, [sessionIsCurrent])

  const applyDocumentRows = useCallback((bankId: string, rows: api.ApiDocument[]) => {
    const pending = pendingDocumentSelection.current
    if (pending && pending.chatVersion !== chatVersionRef.current) {
      pendingDocumentSelection.current = null
    }
    const uploadedId = pending?.bankId === bankId && pending.chatVersion === chatVersionRef.current
      && rows.some(document => document.id === pending.documentId) ? pending.documentId : ''
    if (uploadedId) pendingDocumentSelection.current = null
    const nextId = uploadedId
      || (rows.some(document => document.id === selectedDocRef.current) ? selectedDocRef.current : '')
    if (selectedDocRef.current !== nextId) resetChat()
    selectedDocRef.current = nextId
    setDocs(rows.map(api.mapDocument))
    setSelectedDocId(nextId)
  }, [resetChat])

  // 全局题库与当前文档分别计数，切库不会丢弃仍有效的题库列表。
  const refreshKbs = useCallback(async () => {
    if (!sessionIsCurrent()) return
    const bankVersion = ++bankRequestVersion.current
    let version: number | undefined
    let target: string | undefined
    try {
      const bankRows = (await api.listBanks('all')).filter(bank => bank.status === 'active')
      if (!sessionIsCurrent() || bankVersion !== bankRequestVersion.current) return
      setKbs(bankRows.map(api.mapBankToKnowledgeBase))
      target = selectedKbRef.current
      if (!target) return
      version = ++documentRequestVersion.current
      if (!bankRows.some(bank => bank.id === target)) {
        resetChat()
        selectedDocRef.current = ''
        pendingDocumentSelection.current = null
        selectedKbRef.current = ''
        setSelectedKbId('')
        setSelectedDocId('')
        setDocs([])
        return
      }
      const rows = await api.listDocuments(target)
      if (!sessionIsCurrent() || selectedKbRef.current !== target
        || version !== documentRequestVersion.current) return
      applyDocumentRows(target, rows)
    } catch (error: unknown) {
      if (sessionIsCurrent() && bankVersion === bankRequestVersion.current
        && (version === undefined || version === documentRequestVersion.current)
        && (target === undefined || selectedKbRef.current === target)) {
        showToast(error instanceof Error ? error.message : '刷新题库或文档失败，请重试', 'error')
      }
    }
  }, [applyDocumentRows, resetChat, sessionIsCurrent, showToast])

  const invalidateDocument = useCallback((bankId: string, documentId: string) => {
    if (!sessionIsCurrent() || selectedKbRef.current !== bankId) return
    documentRequestVersion.current += 1
    if (pendingDocumentSelection.current?.documentId === documentId) pendingDocumentSelection.current = null
    setDocs(current => current.filter(document => document.id !== documentId))
    if (selectedDocRef.current === documentId) {
      resetChat()
      selectedDocRef.current = ''
      setSelectedDocId('')
    }
  }, [resetChat, sessionIsCurrent])

  // 催交：学生每 30 秒轮询角标与通知列表
  const loadUrges = useCallback(async () => {
    if (!sessionIsCurrent()) return
    try {
      const feed = await api.listMyUrges()
      if (!sessionIsCurrent()) return
      setUrgeUnread(feed.unread_count)
      setUrgeItems(feed.items)
    } catch {
      /* 轮询失败静默忽略 */
    }
  }, [sessionIsCurrent])

  const clearUrgeBadge = useCallback(() => {
    if (user?.role !== 'student' || !sessionIsCurrent()) return
    void api.clearUrgeBadge().then(loadUrges)
      .catch((err) => showToast(err instanceof Error ? err.message : '清除催交红点失败'))
  }, [user?.role, sessionIsCurrent, loadUrges, showToast])

  const markUrgeRead = useCallback(
    (urgeId: string) => {
      void api
        .markUrgeRead(urgeId)
        .then(loadUrges)
        .catch(() => undefined)
    },
    [loadUrges],
  )

  const deleteUrge = useCallback(
    (urgeId: string) => {
      void api
        .deleteUrge(urgeId)
        .then(() => {
          setUrgeItems((prev) => prev.filter((u) => u.id !== urgeId))
          return loadUrges()
        })
        .catch((err) => showToast(err instanceof Error ? err.message : '删除通知失败'))
    },
    [loadUrges, showToast],
  )

  useEffect(() => {
    if (user?.role !== 'student') {
      setUrgeUnread(0)
      setUrgeItems([])
      return
    }
    void loadUrges()
    const timer = window.setInterval(() => void loadUrges(), 30000)
    return () => window.clearInterval(timer)
  }, [user, loadUrges])

  // 题库通知：每 10 秒轮询未读角标与列表；出现新通知时刷新题库与文档下拉
  const knownNotifIds = useRef<Set<string>>(new Set())
  const notifFirstLoad = useRef(true)
  const selectedKbRef = useRef('')
  selectedKbRef.current = selectedKbId

  const loadBankNotifs = useCallback(async () => {
    if (!sessionIsCurrent()) return
    try {
      const feed = await api.listNotifications()
      if (!sessionIsCurrent()) return
      setBankNotifUnread(feed.unread_count)
      setBankNotifItems(feed.items)
      const fresh = feed.items.filter((n) => !knownNotifIds.current.has(n.id))
      if (!notifFirstLoad.current && fresh.length) {
        void refreshKbs()
      }
      notifFirstLoad.current = false
      knownNotifIds.current = new Set(feed.items.map((n) => n.id))
    } catch {
      /* 轮询失败静默忽略 */
    }
  }, [refreshKbs, sessionIsCurrent])

  const clearBankNotifs = useCallback(() => {
    if (!sessionIsCurrent()) return
    void api.markNotificationsRead().then(loadBankNotifs)
      .catch((err) => showToast(err instanceof Error ? err.message : '清除题库通知红点失败'))
  }, [sessionIsCurrent, loadBankNotifs, showToast])

  const deleteBankNotif = useCallback(
    (id: string) => {
      void api
        .deleteNotification(id)
        .then(() => {
          setBankNotifItems((prev) => prev.filter((n) => n.id !== id))
          return loadBankNotifs()
        })
        .catch((err) => showToast(err instanceof Error ? err.message : '删除通知失败'))
    },
    [loadBankNotifs, showToast],
  )

  useEffect(() => {
    if (!user) return
    void loadBankNotifs()
    const timer = window.setInterval(() => void loadBankNotifs(), 10000)
    return () => window.clearInterval(timer)
  }, [user, loadBankNotifs])

  const requestOpenSpacePaper = useCallback((spaceId: string, paperId: string) => {
    if (!setActiveTab('space')) return
    setPendingSpacePaper({ spaceId, paperId })
    // 切到学习空间页：未打开时挂载 SpaceTab 后由其消费 pending 打开作答标签
  }, [setActiveTab])

  const clearPendingSpacePaper = useCallback(() => setPendingSpacePaper(null), [])

  const switchTab = useCallback(
    (tab: TabKey) => {
      if (!setActiveTab(tab)) return
      if (tab === 'records') void loadRecords()
      if (tab === 'space') {
        void refreshSpaces()
        void loadRecords()
      }
    },
    [loadRecords, refreshSpaces, setActiveTab],
  )

  useEffect(() => {
    if (!user) return
    const version = previewVersionRef.current
    const restoreHistory = !isClearing()
    setProfile(buildProfile(user))
    banksApi.setCurrentUser(user.displayName)
    void (async () => {
      try {
        const [bankRows, latest] = await Promise.all([api.listBanks('all'), api.latestBatch()])
        if (!sessionIsCurrent()) return
        setKbs(bankRows.filter(bank => bank.status === 'active').map(api.mapBankToKnowledgeBase))
        await Promise.all([loadFavorites(), loadRecords(), refreshSpaces(), loadSessions()])
        if (!sessionIsCurrent()) return
        if (restoreHistory && latest.batch_id && version === previewVersionRef.current
          && !isClearing() && !pendingChatPause.current) {
          activeBatchRef.current = latest.batch_id
          setQuestions(latest.questions.map(api.mapQuestion))
        }
      } catch (err) {
        showToast(err instanceof Error ? err.message : '加载数据失败，请检查后端服务')
      }
    })()
  }, [user, loadFavorites, loadRecords, loadSessions, refreshSpaces, sessionIsCurrent, showToast, isClearing])

  useEffect(() => {
    if (!user) return
    void refreshModelSettings().catch(() => undefined)
  }, [user, refreshModelSettings])

  const selectKb = useCallback(
    (id: string) => {
      if (!sessionIsCurrent() || pendingChatPause.current) return
      if (selectedKbRef.current !== id || selectedDocRef.current) resetChat()
      selectedDocRef.current = ''
      const version = ++documentRequestVersion.current
      pendingDocumentSelection.current = null
      selectedKbRef.current = id
      setSelectedKbId(id)
      setSelectedDocId('')
      setDocs([])
      if (!id) return
      void api
        .listDocuments(id)
        .then((rows) => {
          if (sessionIsCurrent() && selectedKbRef.current === id
            && version === documentRequestVersion.current) applyDocumentRows(id, rows)
        })
        .catch((err) => showToast(err instanceof Error ? err.message : '加载文档失败'))
    },
    [applyDocumentRows, resetChat, sessionIsCurrent, showToast],
  )

  const selectDoc = useCallback(
    (id: string) => {
      if (!sessionIsCurrent() || pendingChatPause.current) return
      if (selectedDocRef.current !== id) resetChat()
      selectedDocRef.current = id
      pendingDocumentSelection.current = null
      setSelectedDocId(id)
      if (!id || isClearing()) return
      const version = chatVersionRef.current
      const previewVersion = ++previewVersionRef.current
      const bankId = selectedKbRef.current
      void api.latestBatch(bankId || undefined, id).then((latest) => {
        if (!sessionIsCurrent() || isClearing() || version !== chatVersionRef.current
          || previewVersion !== previewVersionRef.current || selectedKbRef.current !== bankId || selectedDocRef.current !== id) return
        if (latest.batch_id) {
          activeBatchRef.current = latest.batch_id
          setQuestions(latest.questions.map(api.mapQuestion))
          setSelectedIds([])
        }
      }).catch((error: unknown) => {
        if (sessionIsCurrent() && version === chatVersionRef.current
          && previewVersion === previewVersionRef.current) {
          showToast(error instanceof Error ? error.message : '加载历史题目失败', 'error')
        }
      })
    },
    [isClearing, resetChat, sessionIsCurrent, showToast],
  )

  const setMode = useCallback((next: ChatMode) => {
    if (!sessionIsCurrent() || sessionLoadingRef.current || pendingChatPause.current || clearQuestionsFlight.current
      || chatBusyRef.current || confirmRequestRef.current || pendingConfirmRef.current) return
    setModeState(next)
    setModeVisible(true)
    setModeSuggested(null)
  }, [sessionIsCurrent])

  const applyChatResult = useCallback((res: api.ChatMessageResult, previewVersion: number, appendReply = true) => {
    setSessionMode(res.mode)
    setModeVisible(res.kind !== 'reply')
    setModeSuggested(
      res.kind === 'mode_mismatch' && res.suggested_template
      && isChatMode(res.suggested_template) ? res.suggested_template : null,
    )
    setPendingConfirm(res.confirm ?? null)
    if (appendReply) setMessages((prev) => [...prev, { id: `m-${++messageIdRef.current}`, role: 'assistant', text: res.reply }])
    if (res.questions.length && previewVersion === previewVersionRef.current) {
      const incoming = res.questions.map(api.mapQuestion)
      setQuestions((prev) => dedupeQuestions(prev, incoming))
      activeBatchRef.current = res.batch_id
      setSelectedIds([])
      showToast(`已生成 ${incoming.length} 道题目，已合并到「题目预览」`)
    }
  }, [setPendingConfirm, showToast])

  const sendChat = useCallback(
    async (text: string, images: string[] = [], opts?: { switchOnly?: boolean; mode?: ChatMode }) => {
      const trimmed = text.trim()
      if ((!trimmed && !images.length) || sessionLoadingRef.current || pendingChatPause.current || clearQuestionsFlight.current
        || generating || generationRecoveryError || chatBusyRef.current || confirmRequestRef.current
        || pendingConfirmRef.current || !sessionIsCurrent()) return
      if (selectedKbRef.current !== selectedKbId || selectedDocRef.current !== selectedDocId) return
      if (!selectedDocId || !selectedKbId) {
        showToast('请先在右侧选择知识库文档，才能基于知识库出题')
        return
      }
      if (modelSettings && !modelSettings.deepseek_key_configured) {
        apiConfigPromptedRef.current = true
        setApiConfigOpen(true)
        return
      }
      const effectiveMode = opts?.mode ?? mode
      const version = chatVersionRef.current
      const previewVersion = ++previewVersionRef.current
      chatBusyRef.current = true
      const controller = new AbortController()
      chatAbortRef.current = controller
      const isActive = () => sessionIsCurrent() && version === chatVersionRef.current
        && chatAbortRef.current === controller && !controller.signal.aborted
      let poll: number | undefined
      setMessages((prev) => [...prev, {
        id: `m-${++messageIdRef.current}`, role: 'user', text: trimmed,
        images: images.length ? [...images] : undefined,
      }])
      if (!opts?.switchOnly) {
        imageVersionRef.current += 1
        chatImagesRef.current = []
        setChatImages([])
        setInputDraft('')
      }
      setChatProgress(null)
      setChatStartedAt(Date.now())
      setBotThinking(true)
      try {
        let session = chatSessionRef.current
        if (!session || session.bankId !== selectedKbId || session.docId !== selectedDocId) {
          const created = await api.createChatSession(selectedKbId, selectedDocId, controller.signal)
          if (!isActive()) return
          session = { id: created.session_id, bankId: selectedKbId, docId: selectedDocId }
          chatSessionRef.current = session
          setActiveSessionId(created.session_id)
          void loadSessions()
        }
        const sessionId = session.id
        if (!isActive()) return
        const requestId = crypto.randomUUID()
        activeChatTurn.current = { requestId, sessionId, bankId: session.bankId, docId: session.docId }
        poll = window.setInterval(() => {
          if (!isActive()) return
          void api.getChatProgress(sessionId, controller.signal).then((progress) => {
            if (isActive() && progress.active) {
              setChatProgress({ percent: progress.percent, stage: progress.stage })
            }
          }).catch((error: unknown) => {
            if (isActive()) showToast(error instanceof Error ? error.message : '读取出题进度失败')
          })
        }, 1500)
        chatPollRef.current = poll
        const res = await api.sendChatMessage(
          sessionId, trimmed, questions.map((q) => q.stem), controller.signal,
          images, effectiveMode, opts?.switchOnly ?? false, requestId,
        )
        if (!isActive()) return
        applyChatResult(res, previewVersion)
      } catch (error: unknown) {
        if (!isActive()) return
        setMessages((prev) => [...prev, {
          id: `m-${++messageIdRef.current}`, role: 'assistant',
          text: error instanceof Error ? error.message : '服务异常，请稍后再试',
        }])
      } finally {
        if (poll !== undefined) window.clearInterval(poll)
        if (isActive()) {
          chatPollRef.current = null
          chatAbortRef.current = null
          activeChatTurn.current = null
          chatBusyRef.current = false
          setChatProgress(null)
          setChatStartedAt(null)
          setBotThinking(false)
          // 消息已写库：刷新会话列表，让最近消息时间立即更新（避免新会话日期短暂为空）
          void loadSessions()
        }
      }
    },
    [mode, loadSessions, selectedDocId, selectedKbId, questions, generating, generationRecoveryError,
      applyChatResult, sessionIsCurrent, showToast, modelSettings],
  )

  const addChatImages = useCallback((files: File[]) => {
    if (!sessionIsCurrent()) return
    const candidates = files.filter((file) => file.type.startsWith('image/') && file.size <= 5 * 1024 * 1024)
    const oversized = files.filter((file) => file.type.startsWith('image/')).length - candidates.length
    if (oversized > 0) showToast(`有 ${oversized} 张图片超过 5MB，已跳过`)
    if (!candidates.length) return
    const version = chatVersionRef.current
    const imageVersion = imageVersionRef.current
    const isActive = () => sessionIsCurrent() && version === chatVersionRef.current
      && imageVersion === imageVersionRef.current
    void (async () => {
      try {
        const urls = await Promise.all(candidates.map((file) => new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => typeof reader.result === 'string'
            ? resolve(reader.result) : reject(new Error('图片读取结果无效'))
          reader.onerror = () => reject(new Error('图片读取失败'))
          reader.onabort = () => reject(new Error('图片读取已取消'))
          reader.readAsDataURL(file)
        })))
        if (!isActive()) return
        const merged = [...chatImagesRef.current, ...urls]
        if (merged.length > 4) showToast('最多携带 4 张图片')
        chatImagesRef.current = merged.slice(0, 4)
        setChatImages(chatImagesRef.current)
      } catch (error: unknown) {
        if (isActive()) showToast(error instanceof Error ? error.message : '图片读取失败', 'error')
      }
    })()
  }, [sessionIsCurrent, showToast])

  const removeChatImage = useCallback((index: number) => {
    if (!sessionIsCurrent()) return
    chatImagesRef.current = chatImagesRef.current.filter((_, current) => current !== index)
    setChatImages(chatImagesRef.current)
  }, [sessionIsCurrent])

  const confirmOperation = useCallback(async (accepted: boolean) => {
    const target = pendingConfirmRef.current
    const sessionId = chatSessionRef.current?.id
    if (!sessionIsCurrent() || sessionLoadingRef.current || pendingChatPause.current || clearQuestionsFlight.current
      || !target || !sessionId || confirmRequestRef.current
      || chatBusyRef.current) return
    const version = chatVersionRef.current
    const controller = new AbortController()
    confirmRequestRef.current = controller
    const isActive = () => sessionIsCurrent() && version === chatVersionRef.current
      && confirmRequestRef.current === controller && !controller.signal.aborted
      && chatSessionRef.current?.id === sessionId
    let consumed = false
    setConfirmBusy(true)
    try {
      const res = await api.confirmChat(sessionId, target.id, accepted, controller.signal)
      if (!isActive() || pendingConfirmRef.current?.id !== target.id) return
      consumed = true
      setPendingConfirm(null)
      setMessages((prev) => [...prev, { id: `m-${++messageIdRef.current}`, role: 'assistant', text: res.reply }])
      if (accepted && target.entity === 'favorites' && target.action === 'delete') {
        await loadFavorites(isActive)
      } else if (accepted && target.entity === 'papers'
        && (target.action === 'delete' || target.action === 'update')) {
        await loadRecords(isActive)
      }
    } catch (error: unknown) {
      if (isActive()) {
        const message = consumed
          ? '操作已完成，但最新列表加载失败，请刷新页面查看；请勿重复执行该操作'
          : error instanceof Error ? error.message : '确认失败，请重试'
        showToast(message, 'error')
      }
    } finally {
      if (sessionIsCurrent() && version === chatVersionRef.current
        && confirmRequestRef.current === controller) {
        confirmRequestRef.current = null
        setConfirmBusy(false)
      }
    }
  }, [loadFavorites, loadRecords, sessionIsCurrent, setPendingConfirm, showToast])

  const settleChatPause = useCallback(async (turn: ChatTurn) => {
    if (!sessionIsCurrent() || chatPauseController.current) return
    const controller = new AbortController()
    chatPauseController.current = controller
    pendingChatPause.current = turn
    chatBusyRef.current = true
    const version = chatVersionRef.current
    const previewVersion = ++previewVersionRef.current
    const isActive = () => sessionIsCurrent() && !controller.signal.aborted
      && chatPauseController.current === controller
    setBotThinking(true)
    setChatPauseStatus('pending')
    try {
      if (chatPauseKey) sessionStorage.setItem(chatPauseKey, JSON.stringify(turn))
      const requestSignal = () => AbortSignal.any([controller.signal, AbortSignal.timeout(15000)])
      let state = await api.cancelChat(turn.sessionId, turn.requestId, requestSignal())
      while (isActive() && (state.status === 'running' || !state.execution_finished)) {
        await new Promise<void>(resolve => window.setTimeout(resolve, 750))
        if (!isActive()) return
        state = await api.getChatTurn(turn.sessionId, turn.requestId, requestSignal())
      }
      if (!isActive()) return
      if (state.status === 'done' && !state.result) throw new Error('未能恢复本轮已保存的结果')
      const restoring = chatSessionRef.current === null && version === chatVersionRef.current
      if (restoring) {
        const signal = requestSignal()
        const [detail, documents] = await Promise.all([
          api.getChatSession(turn.sessionId, signal),
          api.listDocuments(turn.bankId, signal),
        ])
        let previous: { batch_id: string | null; questions: api.ApiQuestion[] } | null = null
        if (!state.batch_id) {
          const previousBatch = [...detail.messages].reverse().find(message => message.batch_id)?.batch_id
          if (previousBatch) {
            const page = await api.listQuestions({ batch_id: previousBatch, page_size: 100 }, requestSignal())
            previous = { batch_id: previousBatch, questions: page.items }
          } else {
            previous = await api.latestBatch(undefined, undefined, requestSignal())
          }
        }
        if (!isActive()) return
        if (version === chatVersionRef.current) {
          chatSessionRef.current = { id: turn.sessionId, bankId: turn.bankId, docId: turn.docId }
          selectedKbRef.current = turn.bankId
          selectedDocRef.current = turn.docId
          setActiveSessionId(turn.sessionId)
          setSelectedKbId(turn.bankId)
          setSelectedDocId(turn.docId)
          applyDocumentRows(turn.bankId, documents)
          setModeState(detail.mode)
          setSessionMode(detail.mode)
          setModeVisible(detail.messages.length === 0)
          if (previous && previewVersion === previewVersionRef.current) {
            setQuestions(previous.questions.map(api.mapQuestion))
            activeBatchRef.current = previous.batch_id
          }
          setMessages(detail.messages.map(message => ({
            id: message.id, role: message.role, text: message.text,
          })))
        }
      }
      if (state.result && chatSessionRef.current?.id === turn.sessionId
        && version === chatVersionRef.current) {
        applyChatResult(state.result, previewVersion, !restoring)
        showToast('本轮已完成，已恢复结果')
      } else if (chatSessionRef.current?.id === turn.sessionId && version === chatVersionRef.current) {
        const message = state.status === 'canceled' ? '已暂停本次生成。' : '本轮处理已结束，请重新发送。'
        setMessages(prev => [...prev, {
          id: `m-${++messageIdRef.current}`, role: 'assistant', text: message,
        }])
      }
      if (chatPauseKey) sessionStorage.removeItem(chatPauseKey)
      pendingChatPause.current = null
      chatBusyRef.current = false
      setChatPauseStatus(null)
      setBotThinking(false)
      void loadSessions()
    } catch (error: unknown) {
      if (!isActive()) return
      setChatPauseStatus('failed')
      showToast(error instanceof Error ? error.message : '服务端暂停未确认', 'error')
    } finally {
      if (chatPauseController.current === controller) chatPauseController.current = null
    }
  }, [applyChatResult, applyDocumentRows, chatPauseKey, loadSessions, sessionIsCurrent, showToast])

  const pauseChat = useCallback(() => {
    if (!sessionIsCurrent() || chatPauseController.current
      || (!chatBusyRef.current && !pendingChatPause.current)) return
    const turn = pendingChatPause.current ?? activeChatTurn.current
    chatAbortRef.current?.abort()
    if (chatPollRef.current !== null) window.clearInterval(chatPollRef.current)
    chatPollRef.current = null
    chatAbortRef.current = null
    activeChatTurn.current = null
    setChatProgress(null)
    setChatStartedAt(null)
    if (turn) {
      void settleChatPause(turn)
    } else {
      chatBusyRef.current = false
      setBotThinking(false)
    }
  }, [sessionIsCurrent, settleChatPause])

  useEffect(() => {
    if (!chatPauseKey) return
    try {
      const saved = sessionStorage.getItem(chatPauseKey)
      if (!saved) return
      const turn: Partial<ChatTurn> | null = JSON.parse(saved)
      if (turn && typeof turn.requestId === 'string' && typeof turn.sessionId === 'string'
        && typeof turn.bankId === 'string' && typeof turn.docId === 'string') {
        void settleChatPause({
          requestId: turn.requestId, sessionId: turn.sessionId, bankId: turn.bankId, docId: turn.docId,
        })
      }
    } catch (error: unknown) {
      showToast(error instanceof Error ? error.message : '读取暂停记录失败', 'error')
    }
  }, [chatPauseKey, settleChatPause, showToast])

  const retryChat = useCallback((messageId: string) => {
    if (!sessionIsCurrent() || sessionLoadingRef.current || pendingChatPause.current || clearQuestionsFlight.current
      || generating || generationRecoveryError || chatBusyRef.current || confirmRequestRef.current
      || pendingConfirmRef.current || !selectedDocId || !selectedKbId
      || selectedKbRef.current !== selectedKbId || selectedDocRef.current !== selectedDocId) return
    const index = messages.findIndex((message) => message.id === messageId && message.role === 'user')
    if (index < 0) return
    const { text, images } = messages[index]
    setMessages((prev) => prev.slice(0, index))
    void sendChat(text, images ?? [])
  }, [messages, selectedDocId, selectedKbId, sendChat, sessionIsCurrent, generating, generationRecoveryError])

  const editChat = useCallback((messageId: string) => {
    if (!sessionIsCurrent() || sessionLoadingRef.current || pendingChatPause.current || clearQuestionsFlight.current
      || chatBusyRef.current || confirmRequestRef.current || pendingConfirmRef.current) return
    const index = messages.findIndex((message) => message.id === messageId && message.role === 'user')
    if (index < 0) return
    imageVersionRef.current += 1
    setInputDraft(messages[index].text)
    chatImagesRef.current = [...(messages[index].images ?? [])]
    setChatImages(chatImagesRef.current)
    setMessages((prev) => prev.slice(0, index))
  }, [messages, sessionIsCurrent])

  /** 打开历史会话：恢复题库文档选择、消息与最近产出题目，可继续对话 */
  const openSession = useCallback(
    async (target: ChatSessionSummary) => {
      const confirmInFlight = confirmRequestRef.current !== null
      if (!sessionIsCurrent() || chatBusyRef.current || pendingChatPause.current || confirmInFlight
        || pendingConfirmRef.current !== null) return
      const version = ++chatVersionRef.current
      const previewVersion = ++previewVersionRef.current
      sessionLoadingRef.current = true
      const documentVersion = ++documentRequestVersion.current
      const isActive = () => sessionIsCurrent() && version === chatVersionRef.current
      chatAbortRef.current?.abort()
      chatAbortRef.current = null
      confirmRequestRef.current?.abort()
      confirmRequestRef.current = null
      if (chatPollRef.current !== null) {
        window.clearInterval(chatPollRef.current)
        chatPollRef.current = null
      }
      pendingDocumentSelection.current = null
      imageVersionRef.current += 1
      chatImagesRef.current = []
      setBotThinking(false)
      setConfirmBusy(false)
      setChatProgress(null)
      setChatStartedAt(null)
      setPendingConfirm(null)
      setChatImages([])
      setInputDraft('')
      setModeVisible(false)
      setModeSuggested(null)
      // 直接恢复选中态，绕过 selectKb/selectDoc 的 resetChat 副作用
      selectedKbRef.current = target.bankId
      selectedDocRef.current = target.docId
      setSelectedKbId(target.bankId)
      setSelectedDocId(target.docId)
      setDocs([])
      void api.listDocuments(target.bankId).then((rows) => {
        if (isActive() && selectedKbRef.current === target.bankId
          && documentVersion === documentRequestVersion.current) applyDocumentRows(target.bankId, rows)
      }).catch((error: unknown) => {
        if (isActive()) showToast(error instanceof Error ? error.message : '加载文档列表失败', 'error')
      })
      chatSessionRef.current = { id: target.id, bankId: target.bankId, docId: target.docId }
      setActiveSessionId(target.id)
      setQuestions([])
      setSelectedIds([])
      activeBatchRef.current = null
      setSessionLoading(true)
      setMessages([])
      try {
        const detail = await api.getChatSession(target.id)
        if (!isActive() || chatSessionRef.current?.id !== target.id) return
        setModeState(detail.mode)
        setSessionMode(detail.mode)
        setModeVisible(detail.messages.length === 0)
        setMessages(detail.messages.map((m, index) => ({
          id: m.id || `m-his-${index}`,
          role: m.role,
          text: m.text,
        })))
        // 恢复该会话最近一次产出的题目到预览，继续出题时用于查重
        const batchId = [...detail.messages].reverse().find((m) => m.batch_id)?.batch_id ?? null
        if (batchId) {
          try {
            const restored = await api.listQuestions({ batch_id: batchId, page_size: 100 })
            if (!isActive() || chatSessionRef.current?.id !== target.id
              || previewVersion !== previewVersionRef.current) return
            setQuestions(restored.items.map(api.mapQuestion))
            activeBatchRef.current = batchId
            setSelectedIds([])
          } catch (error: unknown) {
            if (isActive() && previewVersion === previewVersionRef.current) {
              showToast(error instanceof Error ? error.message : '恢复历史题目失败，请重新打开会话重试', 'error')
            }
          }
        }
      } catch (error: unknown) {
        if (isActive()) {
          showToast(error instanceof Error ? error.message : '读取历史会话失败', 'error')
          chatSessionRef.current = null
          setActiveSessionId(null)
          setModeState('generate')
          setSessionMode('generate')
          setModeVisible(true)
        }
      } finally {
        // 仅由当前这一次加载负责收尾；用户已切走时交给新的加载流程管理
        if (sessionIsCurrent() && version === chatVersionRef.current) {
          sessionLoadingRef.current = false
          setSessionLoading(false)
        }
      }
    },
    [applyDocumentRows, sessionIsCurrent, setPendingConfirm, showToast],
  )

  /** 新建对话：回到欢迎态；当前会话保留在历史列表中 */
  const startNewChat = useCallback(() => {
    if (!sessionIsCurrent() || pendingChatPause.current) return
    if (!setActiveTab('generate')) return
    resetChat()
  }, [resetChat, sessionIsCurrent, setActiveTab])

  /** 服务端删除成功后更新列表，失败交由确认弹窗显示并重试。 */
  const removeSession = useCallback(
    async (sessionId: string) => {
      if (!sessionIsCurrent()) throw new Error('登录状态已变化，请重新打开页面')
      if (chatSessionRef.current?.id === sessionId
        && (chatBusyRef.current || confirmRequestRef.current || pendingConfirmRef.current)) {
        throw new Error('当前对话正在处理中，请稍后删除')
      }
      await api.deleteChatSession(sessionId)
      if (!sessionIsCurrent()) return
      sessionsRequestVersion.current += 1
      setSessions((prev) => prev.filter((s) => s.id !== sessionId))
      if (chatSessionRef.current?.id === sessionId) resetChat()
      showToast('已删除该对话')
    },
    [resetChat, sessionIsCurrent, showToast],
  )

  const updateQuestion = useCallback(
    async (q: Question) => {
      try {
        const saved = api.mapQuestion(await api.updateQuestionApi(q))
        setQuestions((prev) => prev.map((item) => (item.id === saved.id ? saved : item)))
        setFavorites((prev) => prev.map((item) => (item.id === saved.id ? saved : item)))
        showToast('修改已保存')
      } catch (err) {
        showToast(err instanceof Error ? err.message : '保存失败')
      }
    },
    [showToast],
  )

  const deleteQuestion = useCallback(
    async (id: string) => {
      try {
        await api.deleteQuestionApi(id)
        setQuestions((prev) => prev.filter((item) => item.id !== id))
        setFavorites((prev) => prev.filter((item) => item.id !== id))
        setSelectedIds((prev) => prev.filter((v) => v !== id))
        showToast('已删除该题')
      } catch (err) {
        showToast(err instanceof Error ? err.message : '删除失败')
      }
    },
    [showToast],
  )

  const toggleStar = useCallback(
    async (id: string) => {
      const target = questions.find((q) => q.id === id) ?? favorites.find((q) => q.id === id)
      if (!target) return
      try {
        if (target.starred) {
          await api.removeFavorite(id)
          setQuestions((prev) => prev.map((item) => (item.id === id ? { ...item, starred: false } : item)))
          setFavorites((prev) => prev.filter((item) => item.id !== id))
        } else {
          const defaultGroup = favGroups.find((g) => g.isDefault || g.name === '默认')?.id ?? 'default'
          await api.addFavorite(id, defaultGroup)
          setQuestions((prev) => prev.map((item) => (item.id === id ? { ...item, starred: true } : item)))
          setFavorites((prev) =>
            prev.some((f) => f.id === id)
              ? prev
              : [{ ...target, starred: true, favGroupId: defaultGroup }, ...prev],
          )
        }
      } catch (err) {
        showToast(err instanceof Error ? err.message : '收藏操作失败')
      }
    },
    [questions, favorites, favGroups, showToast],
  )

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]))
  }, [])
  const selectAll = useCallback((ids: string[]) => setSelectedIds(ids), [])
  const clearSelection = useCallback(() => setSelectedIds([]), [])

  const addFavGroup = useCallback(async () => {
    // 默认名去重：未命名、未命名(1)、未命名(2)…
    const nextName = () => {
      const names = new Set(favGroups.map((g) => g.name))
      if (!names.has('未命名')) return '未命名'
      let i = 1
      while (names.has(`未命名(${i})`)) i += 1
      return `未命名(${i})`
    }
    const desired = nextName()
    try {
      const created = await api.createFavoriteGroup(desired)
      const group: FavoriteGroup = { id: created.id, name: created.name, isDefault: false }
      setFavGroups((prev) => [...prev, group])
      return group
    } catch (err) {
      showToast(err instanceof Error ? err.message : '新建分组失败')
      const fallback: FavoriteGroup = { id: `tmp-${Date.now()}`, name: desired, isDefault: false }
      setFavGroups((prev) => [...prev, fallback])
      return fallback
    }
  }, [favGroups, showToast])

  const renameFavGroup = useCallback(
    (id: string, name: string) => {
      const trimmed = name.trim()
      if (!trimmed) return
      void api
        .renameFavoriteGroup(id, trimmed)
        .then(() => setFavGroups((prev) => prev.map((g) => (g.id === id ? { ...g, name: trimmed } : g))))
        .catch((err) => showToast(err instanceof Error ? err.message : '重命名失败'))
    },
    [showToast],
  )

  const removeFavGroup = useCallback(
    (id: string) => {
      void api
        .deleteFavoriteGroup(id)
        .then(() => loadFavorites())
        .catch((err) => showToast(err instanceof Error ? err.message : '删除分组失败'))
    },
    [loadFavorites, showToast],
  )

  const addToFavorites = useCallback(
    (q: Question, groupId: string) => {
      void api
        .addFavorite(q.id, groupId || 'default')
        .then(() => {
          setQuestions((prev) => prev.map((item) => (item.id === q.id ? { ...item, starred: true } : item)))
          setFavorites((prev) =>
            prev.some((f) => f.id === q.id)
              ? prev.map((f) => (f.id === q.id ? { ...q, starred: true, favGroupId: groupId } : f))
              : [{ ...q, starred: true, favGroupId: groupId }, ...prev],
          )
        })
        .catch((err) => showToast(err instanceof Error ? err.message : '收藏失败'))
    },
    [showToast],
  )

  const unfavoriteQuestion = useCallback(
    (questionId: string) => {
      void api
        .removeFavorite(questionId)
        .then(() => {
          setFavorites((prev) => prev.filter((f) => f.id !== questionId))
          setQuestions((prev) => prev.map((item) => (item.id === questionId ? { ...item, starred: false } : item)))
        })
        .catch((err) => showToast(err instanceof Error ? err.message : '取消收藏失败'))
    },
    [showToast],
  )

  const setFavoriteGroup = useCallback(
    (questionId: string, groupId: string) => {
      void api
        .moveFavorite(questionId, groupId)
        .then(() => setFavorites((prev) => prev.map((f) => (f.id === questionId ? { ...f, favGroupId: groupId } : f))))
        .catch((err) => showToast(err instanceof Error ? err.message : '移动分组失败'))
    },
    [showToast],
  )

  const updateProfile = useCallback(
    async (patch: Partial<TeacherProfile>) => {
      if (!user) throw new Error('请先登录')
      const updated = await api.updateProfile({ name: patch.name, gender: patch.gender, phone: patch.phone, school: patch.school })
      if (!sessionIsCurrent()) return
      setProfile(profileFromApi(updated, user.token))
    },
    [user, sessionIsCurrent],
  )

  const publishPaper = useCallback(
    async (
      modules: PaperModule[],
      spaceIds: string[],
      saveRecord: boolean,
      name?: string,
      published = true,
      qs?: Question[],
      examWindow?: ExamWindow | null,
      allowReview = true,
      allowRetake = false,
    ) => {
      if (published && !spaceIds.length) {
        showToast('请至少选择一个学习空间')
        return false
      }
      const pool = orderQuestionsByModules(qs, modules)
      try {
        const created = await api.createPaperApi({
          name: name || `试卷_${new Date().toLocaleDateString('zh-CN')}`,
          questions: pool.map((q) => q.id),
          space_ids: spaceIds,
          save_to_records: saveRecord,
          is_published: published,
          exam_window: examWindow ?? null,
          allow_review: allowReview,
          allow_retake: allowRetake,
        })
        setRecords((prev) => [api.mapPaper(created), ...prev])
        setSelectedIds([])
        showToast(published ? '组卷已发布' : '已保存到组卷记录')
        return true
      } catch (err) {
        showToast(err instanceof Error ? err.message : '组卷失败')
        return false
      }
    },
    [showToast],
  )

  const updateRecord = useCallback(
    (record: AssembleRecord) => {
      const spaceIds = record.spaces
        .map((name) => spaces.find((s) => s.name === name)?.id)
        .filter((x): x is string => !!x)
      void api
        .updatePaperApi(record.id, {
          name: record.name,
          space_ids: spaceIds,
          is_published: !!record.published,
          exam_window: record.examWindow ?? null,
          modules_order: record.modulesOrder,
          allow_review: record.allowReview,
          allow_retake: record.allowRetake,
        })
        .then((updated) => setRecords((prev) => prev.map((r) => (r.id === updated.id ? api.mapPaper(updated) : r))))
        .catch((err) => showToast(err instanceof Error ? err.message : '试卷更新失败'))
    },
    [spaces, showToast],
  )

  const deleteRecord = useCallback(
    async (id: string, opts?: { withPaper?: boolean }) => {
      try {
        // 默认仅删组卷记录（已发布到空间的试卷保留）；withPaper 时整卷删除
        await api.deletePaperApi(id, opts?.withPaper ? 'paper' : 'record')
        if (!sessionIsCurrent()) return false
        await loadRecords()
        if (!sessionIsCurrent()) return false
        showToast(opts?.withPaper ? '试卷已删除' : '组卷记录已删除')
        return true
      } catch (err) {
        showToast(err instanceof Error ? err.message : '删除失败', 'error')
        return false
      }
    },
    [loadRecords, sessionIsCurrent, showToast],
  )

  const deleteRecords = useCallback(
    async (ids: string[]) => {
      if (!ids.length) return false
      try {
        await api.batchDeletePapers(ids)
        if (!sessionIsCurrent()) return false
        await loadRecords()
        if (!sessionIsCurrent()) return false
        showToast(`已删除 ${ids.length} 条组卷记录`)
        return true
      } catch (err) {
        showToast(err instanceof Error ? err.message : '批量删除失败', 'error')
        return false
      }
    },
    [loadRecords, sessionIsCurrent, showToast],
  )

  const deleteRecordQuestions = useCallback(
    async (recordId: string, ids: string[]) => {
      try {
        const updated = await api.removePaperQuestions(recordId, ids)
        if (!sessionIsCurrent()) return false
        recordsRequestVersion.current += 1
        setRecords((prev) => prev.map((r) => (r.id === recordId ? api.mapPaper(updated) : r)))
        showToast('题目已删除，历史作答保留', 'success')
        return true
      } catch (err) {
        showToast(err instanceof Error ? err.message : '删除题目失败', 'error')
        return false
      }
    },
    [sessionIsCurrent, showToast],
  )

  const refreshRecord = useCallback(async (id: string) => {
    const updated = await api.getPaperApi(id)
    if (!sessionIsCurrent()) return
    recordsRequestVersion.current += 1
    setRecords(prev => updated.deleted
      ? prev.filter(record => record.id !== id)
      : prev.map(record => record.id === id ? api.mapPaper(updated) : record))
  }, [sessionIsCurrent])

  const setRecordClosed = useCallback(async (id: string, closed: boolean) => {
    try {
      const updated = await (closed ? api.closePaperApi(id) : api.reopenPaperApi(id))
      if (!sessionIsCurrent()) return false
      recordsRequestVersion.current += 1
      setRecords(prev => prev.map(record => record.id === id ? api.mapPaper(updated) : record))
      showToast(closed ? '试卷已关闭，各空间停止状态保持不变' : '试卷已恢复开放，各空间停止状态保持不变', 'success')
      return true
    } catch (err) {
      showToast(err instanceof Error ? err.message : '试卷状态更新失败', 'error')
      return false
    }
  }, [sessionIsCurrent, showToast])

  const publishRecords = useCallback(
    (ids: string[]) => {
      const targets = records.filter((r) => ids.includes(r.id) && !r.published)
      if (!targets.length) {
        showToast('所选试卷均已发布')
        return
      }
      void Promise.all(
        targets.map(async (r) => {
          const spaceIds = r.spaces
            .map((name) => spaces.find((s) => s.name === name)?.id)
            .filter((x): x is string => !!x)
          if (!spaceIds.length) throw new Error(`「${r.name}」未选择学习空间`)
          const updated = await api.publishPaperApi(r.id, spaceIds, r.examWindow ?? null)
          return api.mapPaper(updated)
        }),
      )
        .then((updated) => {
          setRecords((prev) => prev.map((r) => updated.find((u) => u.id === r.id) ?? r))
          showToast(`已发布 ${targets.length} 份试卷`)
        })
        .catch((err) => showToast(err instanceof Error ? err.message : '发布失败'))
    },
    [records, spaces, showToast],
  )

  /** 服务端成功删除后再清理预览，保留当前会话与消息，失败可原样重试。 */
  const clearQuestions = useCallback((): Promise<void> => {
    if (!sessionIsCurrent()) return Promise.reject(new Error('登录状态已变化，请重新打开页面'))
    if (clearQuestionsFlight.current) return clearQuestionsFlight.current
    if (sessionLoadingRef.current || chatBusyRef.current || confirmRequestRef.current
      || pendingConfirmRef.current || generating || isClearing()) {
      return Promise.reject(new Error('当前任务正在处理中，请等待完成后再清空题目'))
    }
    if (generationRecoveryError) return Promise.reject(new Error(generationRecoveryError))
    const ids = questions.map(question => question.id)
    const version = ++previewVersionRef.current
    setQuestionsClearing(true)
    const flight = Promise.resolve().then(async () => {
      for (let offset = 0; offset < ids.length; offset += QUESTION_DELETE_BATCH_SIZE) {
        if (!sessionIsCurrent()) return
        await api.batchDeleteQuestions(ids.slice(offset, offset + QUESTION_DELETE_BATCH_SIZE))
      }
      if (!sessionIsCurrent()) return
      favoritesRequestVersion.current += 1
      setFavorites(previous => previous.filter(question => !ids.includes(question.id)))
      if (version !== previewVersionRef.current) return
      setQuestions(previous => previous.filter(question => !ids.includes(question.id)))
      setSelectedIds([])
      activeBatchRef.current = null
      showToast(ids.length ? '已清空当前题目，对话记录不受影响' : '当前没有题目')
    }).finally(() => {
      clearQuestionsFlight.current = null
      if (sessionIsCurrent()) setQuestionsClearing(false)
    })
    clearQuestionsFlight.current = flight
    return flight
  }, [questions, sessionIsCurrent, showToast, generating, isClearing, generationRecoveryError])

  const deleteSelected = useCallback(async () => {
    const ids = [...selectedIds]
    if (!ids.length) return
    try {
      await api.batchDeleteQuestions(ids)
      setQuestions((prev) => prev.filter((q) => !ids.includes(q.id)))
      setFavorites((prev) => prev.filter((q) => !ids.includes(q.id)))
      setSelectedIds([])
      showToast(`已删除 ${ids.length} 道题目`)
    } catch (err) {
      showToast(err instanceof Error ? err.message : '批量删除失败')
    }
  }, [selectedIds, showToast])

  const uploadDocument = useCallback(
    async (file: File) => {
      if (!sessionIsCurrent()) return
      if (!selectedKbId) {
        showToast('请先在右侧选择知识库')
        return
      }
      showToast(`正在上传「${file.name}」…`)
      const chatVersion = chatVersionRef.current
      let ingested = false
      try {
        const uploaded = await banksApi.uploadAndWait(selectedKbId, file)
        if (!sessionIsCurrent() || selectedKbRef.current !== selectedKbId) return
        ingested = true
        if (chatVersion === chatVersionRef.current) {
          pendingDocumentSelection.current = { bankId: selectedKbId, documentId: uploaded.id, chatVersion }
        }
        showToast(`「${file.name}」已上传并入库`, 'success')
        const version = ++documentRequestVersion.current
        const rows = await api.listDocuments(selectedKbId)
        if (!sessionIsCurrent() || selectedKbRef.current !== selectedKbId
          || version !== documentRequestVersion.current) return
        applyDocumentRows(selectedKbId, rows)
      } catch (err) {
        const message = err instanceof Error ? err.message : '请重试'
        showToast(ingested ? `文档已入库，但刷新列表失败：${message}` : `上传失败：${message}`, 'error')
      }
    },
    [applyDocumentRows, selectedKbId, sessionIsCurrent, showToast],
  )

  const createSpace = useCallback(
    async (name: string, capacity: number) => {
      const created = await api.createSpace(name, capacity)
      const mapped = api.mapSpace(created)
      setSpaces((prev) => [...prev, mapped])
      showToast(`学习空间「${name}」创建成功`)
      return mapped
    },
    [showToast],
  )

  const joinSpaceByCode = useCallback(
    async (code: string) => {
      try {
        const joined = api.mapSpace(await api.joinSpace(code))
        setSpaces((prev) => (prev.some((s) => s.id === joined.id) ? prev : [...prev, joined]))
        await loadRecords()
        showToast(`已加入学习空间「${joined.name}」`)
        return joined
      } catch (err) {
        showToast(err instanceof Error ? err.message : '加入失败')
        return null
      }
    },
    [loadRecords, showToast],
  )

  const leaveSpace = useCallback(
    (id: string) => {
      void api
        .leaveSpace(id)
        .then(() => setSpaces((prev) => prev.filter((s) => s.id !== id)))
        .catch((err) => showToast(err instanceof Error ? err.message : '退出失败'))
    },
    [showToast],
  )

  const dissolveSpace = useCallback(
    (id: string) => {
      void api
        .dissolveSpace(id)
        .then(() => setSpaces((prev) => prev.filter((s) => s.id !== id)))
        .catch((err) => showToast(err instanceof Error ? err.message : '解散失败'))
    },
    [showToast],
  )

  const removeSpaceMember = useCallback(
    (spaceId: string, name: string) => {
      const target = spaces.find((s) => s.id === spaceId)
      if (!target) return
      void api
        .listSpaceMembers(spaceId)
        .then(async (members) => {
          const member = members.find((m) => m.user.display_name === name)
          if (!member) throw new Error('成员不存在')
          await api.removeSpaceMember(spaceId, member.user.id)
          setSpaces((prev) =>
            prev.map((s) =>
              s.id === spaceId
                ? { ...s, members: s.members.filter((m) => m !== name), memberCount: Math.max(0, s.memberCount - 1) }
                : s,
            ),
          )
        })
        .catch((err) => showToast(err instanceof Error ? err.message : '移出成员失败'))
    },
    [spaces, showToast],
  )

  const renameSpace = useCallback(
    (spaceId: string, newName: string) => {
      void api
        .updateSpace(spaceId, newName)
        .then((updated) => {
          setSpaces((prev) => prev.map((s) => (s.id === spaceId ? api.mapSpace(updated) : s)))
          void loadRecords()
        })
        .catch((err) => showToast(err instanceof Error ? err.message : '重命名失败'))
    },
    [loadRecords, showToast],
  )

  const markRecordAnswered = useCallback((recordId: string, answered: boolean) => {
    setRecords((prev) => prev.map((r) => (r.id === recordId ? { ...r, answered } : r)))
  }, [])

  const requestOpenPaper = useCallback((recordId: string) => setOpenPaperId(recordId), [])
  const clearOpenPaper = useCallback(() => setOpenPaperId(null), [])

  const value: AppState = {
    activeTab,
    setActiveTab: switchTab,
    navCollapsed,
    toggleNav: () => setNavCollapsed((v) => !v),
    historyCollapsed,
    toggleHistory: () => setHistoryCollapsed((v) => !v),
    kbs,
    docs,
    spaces,
    selectedKbId,
    selectedDocId,
    selectKb,
    selectDoc,
    refreshKbs,
    invalidateDocument,
    modelSettings,
    refreshModelSettings,
    apiConfigOpen,
    closeApiConfigModal,
    generating,
    generationClearing,
    generationRecoveryError,
    resetGenerationRecovery,
    retryGenerationCleanup,
    questionsClearing,
    questions,
    favorites,
    favGroups,
    addFavGroup,
    renameFavGroup,
    removeFavGroup,
    addToFavorites,
    unfavoriteQuestion,
    setFavoriteGroup,
    profile,
    updateProfile,
    selectedIds,
    toggleSelect,
    selectAll,
    clearSelection,
    typeFilter,
    setTypeFilter,
    diffFilter,
    setDiffFilter,
    updateQuestion,
    deleteQuestion,
    toggleStar,
    records,
    publishPaper,
    clearQuestions,
    deleteSelected,
    uploadDocument,
    deleteRecord,
    deleteRecords,
    deleteRecordQuestions,
    setRecordClosed,
    refreshRecord,
    publishRecords,
    role: user?.role ?? null,
    createSpace,
    updateRecord,
    joinSpaceByCode,
    leaveSpace,
    dissolveSpace,
    removeSpaceMember,
    renameSpace,
    markRecordAnswered,
    openPaperId,
    requestOpenPaper,
    clearOpenPaper,
    urgeUnread,
    urgeItems,
    clearUrgeBadge,
    markUrgeRead,
    deleteUrge,
    bankNotifUnread,
    bankNotifItems,
    clearBankNotifs,
    deleteBankNotif,
    pendingSpacePaper,
    requestOpenSpacePaper,
    clearPendingSpacePaper,
    messages,
    botThinking,
    sessionLoading,
    inputDraft,
    setInputDraft,
    sessions,
    activeSessionId,
    openSession,
    startNewChat,
    removeSession,
    mode,
    setMode,
    sessionMode,
    modeVisible,
    modeSuggested,
    pendingConfirm,
    confirmBusy,
    confirmOperation,
    chatImages,
    addChatImages,
    removeChatImage,
    sendChat,
    pauseChat,
    chatPauseStatus,
    chatProgress,
    chatStartedAt,
    retryChat,
    editChat,
    toast,
    showToast,
    dismissToast,
  }

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
