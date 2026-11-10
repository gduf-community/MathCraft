import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import * as api from '../api/backend'
import * as banksApi from '../api/banks'
import { getSessionGeneration } from '../api/session'
import type {
  AssembleRecord,
  ChatMessage,
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
import { useAuth } from './AuthContext'
import { useToast } from './ToastContext'
import type { ToastMessage, ToastVariant } from './ToastContext'
import type { AuthRole, AuthUser } from '../api/auth'

export type TabKey = 'generate' | 'preview' | 'bank' | 'records' | 'fav' | 'space' | 'me' | 'settings'

export interface TypeConfig {
  checked: boolean
  count: number
}

const initialTypeConfigs = (): Record<QuestionType, TypeConfig> => ({
  single: { checked: true, count: 5 },
  multiple: { checked: true, count: 3 },
  judge: { checked: false, count: 2 },
  blank: { checked: false, count: 2 },
  compute: { checked: false, count: 2 },
  essay: { checked: false, count: 1 },
})

function buildProfile(user: AuthUser | null): TeacherProfile {
  return {
    name: user?.displayName ?? '',
    avatar: user?.avatarUrl ?? '',
    gender: user?.gender === '男' || user?.gender === '女' ? user.gender : '',
    phone: user?.phone ?? '',
    email: user?.email ?? '',
    teacherId: user?.userNo ?? '',
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
  paramsCollapsed: boolean
  toggleParams: () => void

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

  /** 个人模型设置页的未保存提醒 */
  hasUnsavedChanges: boolean
  setHasUnsavedChanges: (v: boolean) => void
  isSettingsSaving: boolean
  setIsSettingsSaving: (saving: boolean) => void

  typeConfigs: Record<QuestionType, TypeConfig>
  setTypeConfig: (type: QuestionType, patch: Partial<TypeConfig>) => void
  difficulty: Difficulty
  setDifficulty: (d: Difficulty) => void
  knowledgeScope: string
  setKnowledgeScope: (v: string) => void
  generating: boolean
  genProgress: { percent: number; stage: string } | null
  generate: (opts?: { silent?: boolean }) => Promise<boolean>

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
  clearAll: () => void
  deleteSelected: () => Promise<void>
  uploadDocument: (file: File) => Promise<void>
  deleteRecord: (id: string, opts?: { withPaper?: boolean }) => Promise<void>
  deleteRecords: (ids: string[]) => Promise<void>
  deleteRecordQuestions: (recordId: string, ids: string[]) => void
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
  inputDraft: string
  setInputDraft: (v: string) => void
  sendChat: (text: string) => Promise<void>
  /** 中止当前对话请求（服务端仍会跑完，前端不再等结果） */
  pauseChat: () => void
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
  const [paramsCollapsed, setParamsCollapsed] = useState(false)

  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [docs, setDocs] = useState<KbDocument[]>([])
  const [spaces, setSpaces] = useState<StudySpace[]>([])
  const [selectedKbId, setSelectedKbId] = useState('')
  const [selectedDocId, setSelectedDocId] = useState('')

  const [typeConfigs, setTypeConfigs] = useState<Record<QuestionType, TypeConfig>>(initialTypeConfigs)
  const [difficulty, setDifficulty] = useState<Difficulty>('中')
  const [knowledgeScope, setKnowledgeScope] = useState('')
  const [generating, setGenerating] = useState(false)
  const [genProgress, setGenProgress] = useState<{ percent: number; stage: string } | null>(null)

  const [questions, setQuestions] = useState<Question[]>([])
  const [favorites, setFavorites] = useState<Question[]>([])
  const [favGroups, setFavGroups] = useState<FavoriteGroup[]>([])
  const [profile, setProfile] = useState<TeacherProfile>(() => buildProfile(user))
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [typeFilter, setTypeFilter] = useState<QuestionType | 'all'>('all')
  const [diffFilter, setDiffFilter] = useState<Difficulty | 'all'>('all')

  const [records, setRecords] = useState<AssembleRecord[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [chatProgress, setChatProgress] = useState<{ percent: number; stage: string } | null>(null)
  const [chatStartedAt, setChatStartedAt] = useState<number | null>(null)
  const [botThinking, setBotThinking] = useState(false)
  const [inputDraft, setInputDraft] = useState('')
  const [openPaperId, setOpenPaperId] = useState<string | null>(null)
  const [urgeUnread, setUrgeUnread] = useState(0)
  const [urgeItems, setUrgeItems] = useState<api.ApiUrge[]>([])
  const [bankNotifUnread, setBankNotifUnread] = useState(0)
  const [bankNotifItems, setBankNotifItems] = useState<api.ApiNotification[]>([])
  const [pendingSpacePaper, setPendingSpacePaper] = useState<{ spaceId: string; paperId: string } | null>(null)
  // 个人模型设置页的未保存提醒
  const [hasUnsavedChanges, setHasUnsavedChangesState] = useState(false)
  const [isSettingsSaving, setIsSettingsSavingState] = useState(false)
  const settingsDirtyRef = useRef(false)
  const settingsSavingRef = useRef(false)
  const setHasUnsavedChanges = useCallback((dirty: boolean) => {
    settingsDirtyRef.current = dirty
    setHasUnsavedChangesState(dirty)
  }, [])
  const setIsSettingsSaving = useCallback((saving: boolean) => {
    settingsSavingRef.current = saving
    setIsSettingsSavingState(saving)
  }, [])
  const activeBatchRef = useRef<string | null>(null)
  const chatSessionRef = useRef<{ id: string; bankId: string; docId: string } | null>(null)
  const chatAbortRef = useRef<AbortController | null>(null)
  const chatBusyRef = useRef(false)
  const chatPollRef = useRef<number | null>(null)
  const providerSession = useRef(getSessionGeneration())
  const bankRequestVersion = useRef(0)
  const documentRequestVersion = useRef(0)
  const pendingDocumentSelection = useRef<{ bankId: string; documentId: string } | null>(null)
  const mounted = useRef(true)
  const sessionIsCurrent = useCallback(
    () => mounted.current && providerSession.current === getSessionGeneration(),
    [],
  )

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (chatPollRef.current !== null) window.clearInterval(chatPollRef.current)
      chatAbortRef.current?.abort()
    }
  }, [])

  const showToast = useCallback((text: string, variant: ToastVariant = 'info') => {
    if (!sessionIsCurrent()) return
    showSharedToast(text, variant)
  }, [sessionIsCurrent, showSharedToast])

  const setActiveTab = useCallback((tab: TabKey): boolean => {
    if (tab === activeTabRef.current) return true
    if (settingsSavingRef.current) {
      showToast('配置正在保存，请等待完成后再离开', 'error')
      return false
    }
    if (settingsDirtyRef.current && !window.confirm('有未保存的模型配置，离开将丢弃修改。确定离开吗？')) return false
    activeTabRef.current = tab
    setActiveTabState(tab)
    return true
  }, [showToast])

  const loadFavorites = useCallback(async () => {
    if (!sessionIsCurrent()) return
    const [apiFavs, apiGroups] = await Promise.all([api.listFavorites(), api.listFavoriteGroups()])
    if (!sessionIsCurrent()) return
    setFavorites(apiFavs.map(api.mapQuestion))
    setFavGroups(apiGroups.map((g) => ({ id: g.id, name: g.name, isDefault: g.is_default })))
  }, [sessionIsCurrent])

  const loadRecords = useCallback(async () => {
    if (!sessionIsCurrent()) return
    const rows = await api.listPapers()
    if (!sessionIsCurrent()) return
    const details = await Promise.all(
      rows.map(async (p) => {
        try {
          return await api.getPaperApi(p.id)
        } catch {
          return p
        }
      }),
    )
    if (!sessionIsCurrent()) return
    setRecords(details.map(api.mapPaper))
  }, [sessionIsCurrent])

  const refreshSpaces = useCallback(async () => {
    if (!sessionIsCurrent()) return
    const rows = await api.listSpaces()
    if (!sessionIsCurrent()) return
    setSpaces(rows.map(api.mapSpace))
  }, [sessionIsCurrent])

  const applyDocumentRows = useCallback((bankId: string, rows: api.ApiDocument[]) => {
    const pending = pendingDocumentSelection.current
    const uploadedId = pending?.bankId === bankId
      && rows.some(document => document.id === pending.documentId) ? pending.documentId : ''
    if (uploadedId) pendingDocumentSelection.current = null
    setDocs(rows.map(api.mapDocument))
    setSelectedDocId(current => uploadedId
      || (rows.some(document => document.id === current) ? current : ''))
  }, [])

  // 全局题库与当前文档分别计数，切库不会丢弃仍有效的题库列表。
  const refreshKbs = useCallback(async () => {
    if (!sessionIsCurrent()) return
    const bankVersion = ++bankRequestVersion.current
    let version: number | undefined
    let target: string | undefined
    try {
      const bankRows = await api.listBanks('all')
      if (!sessionIsCurrent() || bankVersion !== bankRequestVersion.current) return
      setKbs(bankRows.map(api.mapBankToKnowledgeBase))
      target = selectedKbRef.current
      if (!target) return
      version = ++documentRequestVersion.current
      if (!bankRows.some(bank => bank.id === target)) {
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
  }, [applyDocumentRows, sessionIsCurrent, showToast])

  const invalidateDocument = useCallback((bankId: string, documentId: string) => {
    if (!sessionIsCurrent() || selectedKbRef.current !== bankId) return
    documentRequestVersion.current += 1
    if (pendingDocumentSelection.current?.documentId === documentId) pendingDocumentSelection.current = null
    setDocs(current => current.filter(document => document.id !== documentId))
    setSelectedDocId(current => current === documentId ? '' : current)
  }, [sessionIsCurrent])

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
    setProfile(buildProfile(user))
    banksApi.setCurrentUser(user.displayName)
    void (async () => {
      try {
        const [bankRows, latest] = await Promise.all([api.listBanks('all'), api.latestBatch()])
        if (!sessionIsCurrent()) return
        setKbs(bankRows.map(api.mapBankToKnowledgeBase))
        await Promise.all([loadFavorites(), loadRecords(), refreshSpaces()])
        if (!sessionIsCurrent()) return
        if (latest.batch_id) {
          activeBatchRef.current = latest.batch_id
          setQuestions(latest.questions.map(api.mapQuestion))
        }
      } catch (err) {
        showToast(err instanceof Error ? err.message : '加载数据失败，请检查后端服务')
      }
    })()
  }, [user, loadFavorites, loadRecords, refreshSpaces, sessionIsCurrent, showToast])

  const selectKb = useCallback(
    (id: string) => {
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
    [applyDocumentRows, sessionIsCurrent, showToast],
  )

  const selectDoc = useCallback(
    (id: string) => {
      pendingDocumentSelection.current = null
      setSelectedDocId(id)
      if (!id) return
      void api
        .latestBatch(selectedKbId || undefined, id)
        .then((latest) => {
          if (latest.batch_id) {
            activeBatchRef.current = latest.batch_id
            setQuestions(latest.questions.map(api.mapQuestion))
            setSelectedIds([])
          }
        })
        .catch(() => undefined)
    },
    [selectedKbId],
  )

  const setTypeConfig = useCallback((type: QuestionType, patch: Partial<TypeConfig>) => {
    setTypeConfigs((prev) => ({ ...prev, [type]: { ...prev[type], ...patch } }))
  }, [])

  const runGenerate = useCallback(
    async (opts?: { silent?: boolean }) => {
      if (!sessionIsCurrent()) return false
      const doc = docs.find((d) => d.id === selectedDocId)
      if (!doc) {
        showToast('请先选择知识库文档')
        return false
      }
      const types = (Object.keys(typeConfigs) as QuestionType[])
        .filter((t) => typeConfigs[t].checked && typeConfigs[t].count > 0)
        .map((t) => ({ type: t, count: typeConfigs[t].count }))
      if (!types.length) {
        showToast('请至少勾选一个题型并设置数量')
        return false
      }
      setGenerating(true)
      setGenProgress({ percent: 0, stage: '准备生成' })
      try {
        const started = await api.startGeneration({
          bank_id: selectedKbId,
          document_id: doc.id,
          types,
          difficulty,
          scope: knowledgeScope.trim() || undefined,
          source_mode: 'variant_data',
          existing_stems: questions.map((q) => q.stem),
        })
        if (!sessionIsCurrent()) return false
        let state = await api.getGenerationProgress(started.task_id)
        while (!state.done) {
          if (!sessionIsCurrent()) return false
          setGenProgress({ percent: state.progress, stage: state.stage })
          await new Promise((r) => setTimeout(r, 500))
          if (!sessionIsCurrent()) return false
          state = await api.getGenerationProgress(started.task_id)
        }
        if (!sessionIsCurrent()) return false
        if (state.error?.message) throw new Error(state.error.message)
        const incoming = state.questions.map(api.mapQuestion)
        setQuestions((prev) => dedupeQuestions(prev, incoming))
        activeBatchRef.current = state.batch_id
        setSelectedIds([])
        setTypeFilter('all')
        setDiffFilter('all')
        if (!opts?.silent) {
          const rv = state.review
          const detail: string[] = []
          if (rv?.duplicates) detail.push(`去重 ${rv.duplicates} 题`)
          if (rv?.repaired) detail.push(`修补 ${rv.repaired} 题`)
          if (rv?.regenerated) detail.push(`重出 ${rv.regenerated} 题`)
          const extra = detail.length ? `（${detail.join('，')}）` : ''
          showToast(`已生成 ${incoming.length} 道题目${extra}`)
        }
        setActiveTab('preview')
        return true
      } catch (err) {
        showToast(err instanceof Error ? err.message : '生成失败，请检查后端服务')
        return false
      } finally {
        setGenerating(false)
        setGenProgress(null)
      }
    },
    [docs, selectedDocId, typeConfigs, difficulty, knowledgeScope, questions, selectedKbId, sessionIsCurrent, setActiveTab, showToast],
  )

  const sendChat = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || chatBusyRef.current || !sessionIsCurrent()) return
      if (!selectedDocId || !selectedKbId) {
        showToast('请先在右侧选择知识库文档，才能基于知识库出题')
        return
      }
      chatBusyRef.current = true
      const controller = new AbortController()
      chatAbortRef.current = controller
      const isActive = () => sessionIsCurrent() && chatAbortRef.current === controller && !controller.signal.aborted
      let poll: number | undefined
      setMessages((prev) => [...prev, { id: `m-${Date.now()}`, role: 'user', text: trimmed }])
      setChatStartedAt(Date.now())
      setBotThinking(true)
      try {
        let session = chatSessionRef.current
        if (!session || session.bankId !== selectedKbId || session.docId !== selectedDocId) {
          const created = await api.createChatSession(selectedKbId, selectedDocId)
          if (!isActive()) return
          session = { id: created.session_id, bankId: selectedKbId, docId: selectedDocId }
          chatSessionRef.current = session
        }
        const sessionId = session.id
        if (!isActive()) return
        poll = window.setInterval(() => {
          if (!isActive()) return
          void api.getChatProgress(sessionId).then((p) => {
            if (isActive() && p.active) setChatProgress({ percent: p.percent, stage: p.stage })
          }).catch((err) => {
            if (isActive()) showToast(err instanceof Error ? err.message : '读取出题进度失败')
          })
        }, 1500)
        chatPollRef.current = poll
        const res = await api.sendChatMessage(
          sessionId, trimmed, questions.map((q) => q.stem), controller.signal,
        )
        if (!isActive()) return
        setMessages((prev) => [...prev, { id: `m-${Date.now()}-a`, role: 'assistant', text: res.reply }])
        if (res.questions.length) {
          const incoming = res.questions.map(api.mapQuestion)
          // 对话出题与快速出题合并保留，互不覆盖
          setQuestions((prev) => dedupeQuestions(prev, incoming))
          activeBatchRef.current = res.batch_id
          setSelectedIds([])
          showToast(`已生成 ${incoming.length} 道题目，已合并到「题目预览」`)
        }
      } catch (err) {
        if (!sessionIsCurrent() || chatAbortRef.current !== controller) return
        const aborted = err instanceof DOMException && err.name === 'AbortError'
        setMessages((prev) => [
          ...prev,
          {
            id: `m-${Date.now()}-a`,
            role: 'assistant',
            text: aborted ? '已暂停本次生成。' : err instanceof Error ? err.message : '服务异常，请稍后再试',
          },
        ])
      } finally {
        if (poll !== undefined) window.clearInterval(poll)
        if (chatAbortRef.current === controller) {
          chatPollRef.current = null
          chatAbortRef.current = null
          chatBusyRef.current = false
          setChatProgress(null)
          setChatStartedAt(null)
          setBotThinking(false)
        }
      }
    },
    [selectedDocId, selectedKbId, questions, sessionIsCurrent, showToast],
  )

  const pauseChat = useCallback(() => {
    if (!sessionIsCurrent() || !chatBusyRef.current) return
    const sessionId = chatSessionRef.current?.id
    if (sessionId) void api.cancelChat(sessionId)
      .catch((err) => showToast(err instanceof Error ? err.message : '服务端暂停未确认'))
    chatAbortRef.current?.abort()
    if (chatPollRef.current !== null) window.clearInterval(chatPollRef.current)
    chatPollRef.current = null
    chatAbortRef.current = null
    chatBusyRef.current = false
    setBotThinking(false)
    setChatProgress(null)
    setChatStartedAt(null)
    setMessages((prev) => [...prev, { id: `m-${Date.now()}-paused`, role: 'assistant', text: '已暂停本次生成。' }])
  }, [sessionIsCurrent, showToast])

  const retryChat = useCallback(
    (messageId: string) => {
      if (chatBusyRef.current) return
      const index = messages.findIndex((m) => m.id === messageId)
      if (index < 0) return
      const text = messages[index].text
      setMessages((prev) => prev.slice(0, index))
      void sendChat(text)
    },
    [messages, sendChat],
  )

  const editChat = useCallback(
    (messageId: string) => {
      if (chatBusyRef.current) return
      const index = messages.findIndex((m) => m.id === messageId)
      if (index < 0) return
      setInputDraft(messages[index].text)
      setMessages((prev) => prev.slice(0, index))
    },
    [messages],
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
        setRecords((prev) => prev.filter((r) => r.id !== id))
        showToast(opts?.withPaper ? '试卷已删除' : '组卷记录已删除')
      } catch (err) {
        showToast(err instanceof Error ? err.message : '删除失败')
      }
    },
    [showToast],
  )

  const deleteRecords = useCallback(
    async (ids: string[]) => {
      if (!ids.length) return
      try {
        await api.batchDeletePapers(ids)
        setRecords((prev) => prev.filter((r) => !ids.includes(r.id)))
        showToast(`已删除 ${ids.length} 条组卷记录`)
      } catch (err) {
        showToast(err instanceof Error ? err.message : '批量删除失败')
      }
    },
    [showToast],
  )

  const deleteRecordQuestions = useCallback(
    (recordId: string, ids: string[]) => {
      void api
        .removePaperQuestions(recordId, ids)
        .then((updated) =>
          setRecords((prev) => prev.map((r) => (r.id === recordId ? api.mapPaper(updated) : r))),
        )
        .catch((err) => showToast(err instanceof Error ? err.message : '删除题目失败'))
    },
    [showToast],
  )

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

  const clearAll = useCallback(() => {
    if (!setActiveTab('generate')) return
    if (questions.length) {
      void api.batchDeleteQuestions(questions.map((q) => q.id)).catch(() => undefined)
    }
    if (chatSessionRef.current) {
      void api.deleteChatSession(chatSessionRef.current.id).catch(() => undefined)
      chatSessionRef.current = null
    }
    setQuestions([])
    setSelectedIds([])
    setMessages([])
    setInputDraft('')
    activeBatchRef.current = null
    showToast('已清空全部题目与对话记录')
  }, [questions, setActiveTab, showToast])

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
      let ingested = false
      try {
        const uploaded = await banksApi.uploadAndWait(selectedKbId, file)
        if (!sessionIsCurrent() || selectedKbRef.current !== selectedKbId) return
        ingested = true
        pendingDocumentSelection.current = { bankId: selectedKbId, documentId: uploaded.id }
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
    paramsCollapsed,
    toggleParams: () => setParamsCollapsed((v) => !v),
    kbs,
    docs,
    spaces,
    selectedKbId,
    selectedDocId,
    selectKb,
    selectDoc,
    refreshKbs,
    invalidateDocument,
    hasUnsavedChanges,
    setHasUnsavedChanges,
    isSettingsSaving,
    setIsSettingsSaving,
    typeConfigs,
    setTypeConfig,
    difficulty,
    setDifficulty,
    knowledgeScope,
    setKnowledgeScope,
    generating,
    genProgress,
    generate: runGenerate,
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
    clearAll,
    deleteSelected,
    uploadDocument,
    deleteRecord,
    deleteRecords,
    deleteRecordQuestions,
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
    inputDraft,
    setInputDraft,
    sendChat,
    pauseChat,
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
