import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import * as api from '../api/backend'
import * as banksApi from '../api/banks'
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
    gender: (user?.gender as '男' | '女') || '男',
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

  /** 设置页（社区设置模块）：定位引擎与未保存提醒 */
  settingsTarget: { engine: string; request: number } | null
  openEngineSettings: (engine?: string) => void
  hasUnsavedChanges: boolean
  setHasUnsavedChanges: (v: boolean) => void
  /** 设置页保存后刷新题库列表的别名入口 */
  refreshKnowledgeBases: () => Promise<void>

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
  /** 通知「立即查看」：跳转到学习空间中该试卷的作答标签页 */
  pendingSpacePaper: { spaceId: string; paperId: string } | null
  requestOpenSpacePaper: (spaceId: string, paperId: string) => void
  clearPendingSpacePaper: () => void

  messages: ChatMessage[]
  botThinking: boolean
  inputDraft: string
  setInputDraft: (v: string) => void
  sendChat: (text: string) => Promise<void>

  toast: { id: number; text: string } | null
  showToast: (text: string) => void
}

const AppContext = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const user = useAuth().user
  const [activeTab, setActiveTab] = useState<TabKey>('generate')
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
  const [botThinking, setBotThinking] = useState(false)
  const [inputDraft, setInputDraft] = useState('')
  const [toast, setToast] = useState<{ id: number; text: string } | null>(null)
  const [openPaperId, setOpenPaperId] = useState<string | null>(null)
  const [urgeUnread, setUrgeUnread] = useState(0)
  const [urgeItems, setUrgeItems] = useState<api.ApiUrge[]>([])
  const [pendingSpacePaper, setPendingSpacePaper] = useState<{ spaceId: string; paperId: string } | null>(null)
  // 设置页：跳转定位（引擎）与未保存提醒
  const [settingsTarget, setSettingsTarget] = useState<{ engine: string; request: number } | null>(null)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const toastTimer = useRef<number | undefined>(undefined)
  const activeBatchRef = useRef<string | null>(null)
  const chatSessionRef = useRef<{ id: string; bankId: string; docId: string } | null>(null)

  const showToast = useCallback((text: string) => {
    // 相同文案连续触发时只重置计时，不重新挂载，避免 toast 重复闪现
    setToast((prev) => (prev?.text === text ? prev : { id: Date.now(), text }))
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 2600)
  }, [])

  const loadFavorites = useCallback(async () => {
    const [apiFavs, apiGroups] = await Promise.all([api.listFavorites(), api.listFavoriteGroups()])
    setFavorites(apiFavs.map(api.mapQuestion))
    setFavGroups(apiGroups.map((g) => ({ id: g.id, name: g.name, isDefault: g.is_default })))
  }, [])

  const loadRecords = useCallback(async () => {
    const rows = await api.listPapers()
    const details = await Promise.all(
      rows.map(async (p) => {
        try {
          return await api.getPaperApi(p.id)
        } catch {
          return p
        }
      }),
    )
    setRecords(details.map(api.mapPaper))
  }, [])

  const refreshSpaces = useCallback(async () => {
    const rows = await api.listSpaces()
    setSpaces(rows.map(api.mapSpace))
  }, [])

  // 题库列表刷新：新建/加入/退出题库后侧边栏「选择题库文档」实时同步
  const refreshKbs = useCallback(async () => {
    try {
      const bankRows = await api.listBanks('all')
      setKbs(bankRows.map(api.mapBankToKnowledgeBase))
    } catch {
      /* 刷新失败静默忽略，下次进入页面会重新加载 */
    }
  }, [])

  // 催交：学生每 30 秒轮询角标与通知列表
  const loadUrges = useCallback(async () => {
    try {
      const feed = await api.listMyUrges()
      setUrgeUnread(feed.unread_count)
      setUrgeItems(feed.items)
    } catch {
      /* 轮询失败静默忽略 */
    }
  }, [])

  const clearUrgeBadge = useCallback(() => {
    void api.clearUrgeBadge().then(loadUrges).catch(() => undefined)
  }, [loadUrges])

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

  const requestOpenSpacePaper = useCallback((spaceId: string, paperId: string) => {
    setPendingSpacePaper({ spaceId, paperId })
    // 切到学习空间页：未打开时挂载 SpaceTab 后由其消费 pending 打开作答标签
    setActiveTab('space')
  }, [])

  const clearPendingSpacePaper = useCallback(() => setPendingSpacePaper(null), [])

  /** 从知识库连接等入口跳转到设置页并定位到指定引擎 */
  const openEngineSettings = useCallback((engine = 'llamaindex') => {
    setSettingsTarget((previous) => ({ engine, request: (previous?.request ?? 0) + 1 }))
    setActiveTab('settings')
  }, [])

  const switchTab = useCallback(
    (tab: TabKey) => {
      setActiveTab(tab)
      if (tab === 'settings') setSettingsTarget(null)
      if (tab === 'records') void loadRecords()
      if (tab === 'space') {
        void refreshSpaces()
        void loadRecords()
      }
    },
    [loadRecords, refreshSpaces],
  )

  useEffect(() => {
    if (!user) return
    setProfile(buildProfile(user))
    banksApi.setCurrentUser(user.displayName)
    void (async () => {
      try {
        const [bankRows, latest] = await Promise.all([api.listBanks('all'), api.latestBatch()])
        setKbs(bankRows.map(api.mapBankToKnowledgeBase))
        await Promise.all([loadFavorites(), loadRecords(), refreshSpaces()])
        if (latest.batch_id) {
          activeBatchRef.current = latest.batch_id
          setQuestions(latest.questions.map(api.mapQuestion))
        }
      } catch (err) {
        showToast(err instanceof Error ? err.message : '加载数据失败，请检查后端服务')
      }
    })()
  }, [user, loadFavorites, loadRecords, refreshSpaces, showToast])

  const selectKb = useCallback(
    (id: string) => {
      setSelectedKbId(id)
      setSelectedDocId('')
      setDocs([])
      if (!id) return
      void api
        .listDocuments(id)
        .then((rows) => setDocs(rows.map(api.mapDocument)))
        .catch((err) => showToast(err instanceof Error ? err.message : '加载文档失败'))
    },
    [showToast],
  )

  const selectDoc = useCallback(
    (id: string) => {
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
        let state = await api.getGenerationProgress(started.task_id)
        while (!state.done) {
          setGenProgress({ percent: state.progress, stage: state.stage })
          await new Promise((r) => setTimeout(r, 500))
          state = await api.getGenerationProgress(started.task_id)
        }
        if (state.error?.message) throw new Error(state.error.message)
        const incoming = state.questions.map(api.mapQuestion)
        setQuestions((prev) => dedupeQuestions(prev, incoming))
        activeBatchRef.current = state.batch_id
        setSelectedIds([])
        setTypeFilter('all')
        setDiffFilter('all')
        if (!opts?.silent) showToast(`已生成 ${incoming.length} 道题目`)
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
    [docs, selectedDocId, typeConfigs, difficulty, knowledgeScope, questions, selectedKbId, showToast],
  )

  const sendChat = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return
      if (!selectedDocId || !selectedKbId) {
        showToast('请先在右侧选择知识库文档，才能基于知识库出题')
        return
      }
      setMessages((prev) => [...prev, { id: `m-${Date.now()}`, role: 'user', text: trimmed }])
      setBotThinking(true)
      try {
        let session = chatSessionRef.current
        if (!session || session.bankId !== selectedKbId || session.docId !== selectedDocId) {
          const created = await api.createChatSession(selectedKbId, selectedDocId)
          session = { id: created.session_id, bankId: selectedKbId, docId: selectedDocId }
          chatSessionRef.current = session
        }
        const res = await api.sendChatMessage(session.id, trimmed, questions.map((q) => q.stem))
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
        setMessages((prev) => [
          ...prev,
          { id: `m-${Date.now()}-a`, role: 'assistant', text: err instanceof Error ? err.message : '服务异常，请稍后再试' },
        ])
      } finally {
        setBotThinking(false)
      }
    },
    [selectedDocId, selectedKbId, questions, showToast],
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
      const updated = await api.updateProfile({ name: patch.name, gender: patch.gender, phone: patch.phone || undefined, school: patch.school })
      setProfile(profileFromApi(updated, user.token))
    },
    [user],
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
    setActiveTab('generate')
    showToast('已清空全部题目与对话记录')
  }, [questions, showToast])

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
      if (!selectedKbId) {
        showToast('请先在右侧选择知识库')
        return
      }
      showToast(`正在上传「${file.name}」…`)
      try {
        await banksApi.uploadAndWait(selectedKbId, file)
        const rows = await api.listDocuments(selectedKbId)
        setDocs(rows.map(api.mapDocument))
        const match = rows.find((d) => d.name === file.name)
        if (match) setSelectedDocId(match.id)
        showToast(`「${file.name}」已上传并入库`)
      } catch (err) {
        showToast(err instanceof Error ? err.message : '上传失败')
      }
    },
    [selectedKbId, showToast],
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
    settingsTarget,
    openEngineSettings,
    hasUnsavedChanges,
    setHasUnsavedChanges,
    refreshKnowledgeBases: refreshKbs,
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
    pendingSpacePaper,
    requestOpenSpacePaper,
    clearPendingSpacePaper,
    messages,
    botThinking,
    inputDraft,
    setInputDraft,
    sendChat,
    toast,
    showToast,
  }

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
