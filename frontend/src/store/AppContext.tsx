import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api/client'
import { chat } from '../api/httpAdapter'
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
import defaultAvatar from '../assets/teacher_avatar.png'
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

interface AppState {
  // 布局
  activeTab: TabKey
  setActiveTab: (t: TabKey) => void
  /** 设置页未保存更改标记（切换导航与离开页面前确认） */
  hasUnsavedChanges: boolean
  setHasUnsavedChanges: (dirty: boolean) => void
  /** 设置页跳转目标：引擎名 + 请求序号，用于重复跳转时强制重挂载 */
  settingsTarget: { engine: string; request: number } | null
  openEngineSettings: (engine?: string) => void
  /** 重新拉取题库（知识库）列表，供设置页改动后刷新 */
  refreshKnowledgeBases: () => Promise<void>
  navCollapsed: boolean
  toggleNav: () => void
  paramsCollapsed: boolean
  toggleParams: () => void

  // 知识库与文档
  kbs: KnowledgeBase[]
  docs: KbDocument[]
  spaces: StudySpace[]
  selectedKbId: string
  selectedDocId: string
  selectKb: (id: string) => void
  selectDoc: (id: string) => void
  // 出题参数
  typeConfigs: Record<QuestionType, TypeConfig>
  setTypeConfig: (type: QuestionType, patch: Partial<TypeConfig>) => void
  difficulty: Difficulty
  setDifficulty: (d: Difficulty) => void
  knowledgeScope: string
  setKnowledgeScope: (v: string) => void
  generating: boolean
  /** 生成进度：null=空闲；percent 为后端打点的真实百分比 */
  genProgress: { percent: number; stage: string } | null
  generate: (opts?: { silent?: boolean }) => Promise<boolean>

  // 题目与筛选
  questions: Question[]
  favorites: Question[]
  /** 收藏分组：default 组固定存在 */
  favGroups: FavoriteGroup[]
  addFavGroup: () => FavoriteGroup
  renameFavGroup: (id: string, name: string) => void
  removeFavGroup: (id: string) => void
  /** 点亮收藏：写入收藏夹并归入指定分组，同步全局题目星标 */
  addToFavorites: (q: Question, groupId: string) => void
  /** 取消收藏：从收藏夹移除并同步各处星标 */
  unfavoriteQuestion: (questionId: string) => void
  /** 已收藏题目更换分组 */
  setFavoriteGroup: (questionId: string, groupId: string) => void
  profile: TeacherProfile
  updateProfile: (patch: Partial<TeacherProfile>) => void
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

  // 组卷
  records: AssembleRecord[]
  publishPaper: (
    modules: PaperModule[],
    spaceIds: string[],
    saveRecord: boolean,
    name?: string,
    published?: boolean,
    questions?: Question[],
    examWindow?: ExamWindow | null,
  ) => Promise<boolean>
  clearAll: () => void
  deleteSelected: () => Promise<void>
  uploadDocument: (file: File) => Promise<void>
  deleteRecord: (id: string) => Promise<void>
  deleteRecordQuestions: (recordId: string, ids: string[]) => void
  publishRecords: (ids: string[]) => void
  /** 当前登录角色；null 表示未登录（理论上主应用仅在登录后挂载） */
  role: AuthRole | null
  createSpace: (name: string, capacity: number) => StudySpace
  updateRecord: (record: AssembleRecord) => void
  /** 按空间编号加入空间（学生演示流程），成功返回空间，编号不存在返回 null */
  joinSpaceByCode: (code: string) => StudySpace | null
  /** 学生退出空间：从空间列表移除 */
  leaveSpace: (id: string) => void
  /** 教师解散空间：空间整体移除（演示态），关联的组卷记录保留 */
  dissolveSpace: (id: string) => void
  removeSpaceMember: (spaceId: string, name: string) => void
  renameSpace: (spaceId: string, newName: string) => void
  /** 学生交卷后标记作答状态（重新作答时置回 false） */
  markRecordAnswered: (recordId: string, answered: boolean) => void
  openPaperId: string | null
  requestOpenPaper: (recordId: string) => void
  clearOpenPaper: () => void

  // 对话
  messages: ChatMessage[]
  botThinking: boolean
  inputDraft: string
  setInputDraft: (v: string) => void
  sendChat: (text: string) => Promise<void>

  // 全局提示
  toast: { id: number; text: string } | null
  showToast: (text: string) => void
}

const AppContext = createContext<AppState | null>(null)

/** 按登录身份生成教师资料：学生用姓氏头像（avatar 留空），教师沿用默认头像 */
function buildProfile(user: AuthUser | null): TeacherProfile {
  if (user?.role === 'student') {
    return {
      name: user.displayName,
      avatar: '',
      gender: '男',
      phone: '13800138000',
      email: 'xiaoming@stu.edu.cn',
      teacherId: 'ST20250001',
      school: '广东金融学院',
      identity: user.identity,
    }
  }
  return {
    name: user?.displayName ?? '张老师',
    avatar: defaultAvatar,
    gender: '男',
    phone: '13800138000',
    email: 'zhang@163.com',
    teacherId: 'TK20240001',
    school: '广东金融学院',
    identity: user?.identity ?? '教师',
  }
}

/** AppProvider 挂载在 AuthProvider 内，登录态已就绪 */
function useAuthUser(): AuthUser | null {
  return useAuth().user
}

export function AppProvider({ children }: { children: ReactNode }) {
  const user = useAuthUser()
  const [activeTab, setActiveTabState] = useState<TabKey>('generate')
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [settingsTarget, setSettingsTarget] = useState<{ engine: string; request: number } | null>(null)
  const dirtyRef = useRef(false)
  dirtyRef.current = hasUnsavedChanges
  const confirmLeave = useCallback(
    () => !dirtyRef.current || window.confirm('当前页面有未保存的更改，确定离开并放弃这些更改？'),
    [],
  )
  const setActiveTab = useCallback(
    (tab: TabKey) => {
      if (tab === activeTab || !confirmLeave()) return
      setHasUnsavedChanges(false)
      if (tab === 'settings') setSettingsTarget(null)
      setActiveTabState(tab)
    },
    [activeTab, confirmLeave],
  )
  /** 从知识库连接等入口跳转到设置页并定位到指定引擎 */
  const openEngineSettings = useCallback(
    (engine = 'llamaindex') => {
      if (!confirmLeave()) return
      setHasUnsavedChanges(false)
      setSettingsTarget((previous) => ({ engine, request: (previous?.request ?? 0) + 1 }))
      setActiveTabState('settings')
    },
    [confirmLeave],
  )
  /** 设置页保存模型配置后刷新题库（知识库）列表 */
  const refreshKnowledgeBases = useCallback(async () => {
    setKbs(await api.listAllBanks())
  }, [])

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [])
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
  // 收藏分组：default 组固定存在，其余由用户在收藏页新建
  const [favGroups, setFavGroups] = useState<FavoriteGroup[]>([{ id: 'default', name: '默认' }])
  const [profile, setProfile] = useState<TeacherProfile>(() => buildProfile(useAuthUser()))
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [typeFilter, setTypeFilter] = useState<QuestionType | 'all'>('all')
  const [diffFilter, setDiffFilter] = useState<Difficulty | 'all'>('all')

  const [records, setRecords] = useState<AssembleRecord[]>([])

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [botThinking, setBotThinking] = useState(false)
  const [inputDraft, setInputDraft] = useState('')

  const [toast, setToast] = useState<{ id: number; text: string } | null>(null)
  const toastTimer = useRef<number | undefined>(undefined)
  // 对话出题的槽位状态，由后端每轮回传，前端原样带回
  const chatSlotState = useRef<Record<string, unknown>>({})

  const showToast = useCallback((text: string) => {
    setToast({ id: Date.now(), text })
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 2600)
  }, [])

  // 初始化：加载题库联动知识库与学习空间；知识库默认不选中（下拉显示未选择）
  useEffect(() => {
    void (async () => {
      const [kbList, spaceList] = await Promise.all([api.listAllBanks(), api.listStudySpaces()])
      // 题库联动端点异常时回退到内置知识库列表
      const bases = kbList.length ? kbList : await api.listKnowledgeBases()
      setKbs(bases)
      setSpaces(spaceList)
    })()
  }, [])

  const selectKb = useCallback(async (id: string) => {
    setSelectedKbId(id)
    setSelectedDocId('')
    // 后端未收录该题库时视为空文档列表，不阻塞界面
    setDocs(await api.listDocuments(id).catch(() => []))
  }, [])

  const selectDoc = useCallback((id: string) => setSelectedDocId(id), [])

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
        const list = await api.generateQuestions(
          {
            // 题库即知识库：把所选题库 id 传给后端检索对应 collection
            kbId: selectedKbId || undefined,
            docId: doc.id,
            docName: doc.name,
            difficulty,
            types,
            scope: knowledgeScope.trim() || undefined,
            // 全局去重：把当前已有题目题干传给后端
            existingStems: questions.map((q) => q.stem),
          },
          // 后端打点的真实进度：百分比 + 阶段文案
          (percent, stage) => setGenProgress({ percent, stage }),
        )
        setGenProgress(null)
        // 追加合并，不覆盖已出的题目（对话出题与参数出题共存）
        setQuestions((prev) => [...prev, ...list.filter((n) => !prev.some((p) => p.id === n.id))])
        setSelectedIds([])
        setTypeFilter('all')
        setDiffFilter('all')
        if (!opts?.silent) showToast(`已生成 ${list.length} 道题目，累计 ${questions.length + list.length} 道`)
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
    [docs, selectedDocId, typeConfigs, difficulty, knowledgeScope, questions, showToast],
  )

  const sendChat = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return
      // 未选择知识库文档时禁止对话出题
      if (!selectedDocId) {
        showToast('请先在右侧选择知识库文档，才能基于知识库出题')
        return
      }
      setMessages((prev) => [...prev, { id: `m-${Date.now()}`, role: 'user', text: trimmed }])
      setBotThinking(true)
      try {
        const res = await chat({
          kb_id: selectedKbId || 'kb-math',
          doc_id: selectedDocId,
          message: trimmed,
          history: messages.slice(-6).map((m) => ({ role: m.role, text: m.text })),
          slot_state: chatSlotState.current,
          // 全局去重：把当前已有题目题干传给后端
          existing_stems: questions.map((q) => q.stem),
        })
        chatSlotState.current = res.slot_state
        setMessages((prev) => [...prev, { id: `m-${Date.now()}-a`, role: 'assistant', text: res.reply }])
        if (res.questions?.length) {
          // 对话路径不强制切页：AI 回复先可见，题目已在「题目预览」标签页等候
          setQuestions(res.questions)
          setSelectedIds([])
          setTypeFilter('all')
          setDiffFilter('all')
          showToast(`已生成 ${res.questions.length} 道题目，已同步到「题目预览」标签页`)
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
    [selectedDocId, selectedKbId, messages, questions, showToast],
  )

  const updateQuestion = useCallback(
    async (q: Question) => {
      const saved = await api.updateQuestion(q)
      setQuestions((prev) => prev.map((item) => (item.id === saved.id ? saved : item)))
      // 收藏夹中的副本同步更新
      setFavorites((prev) => prev.map((item) => (item.id === saved.id ? saved : item)))
      showToast('修改已保存')
    },
    [showToast],
  )

  const deleteQuestion = useCallback(
    async (id: string) => {
      await api.deleteQuestion(id)
      setQuestions((prev) => prev.filter((item) => item.id !== id))
      setFavorites((prev) => prev.filter((item) => item.id !== id))
      setSelectedIds((prev) => prev.filter((v) => v !== id))
      showToast('已删除该题')
    },
    [showToast],
  )

  const toggleStar = useCallback(
    async (id: string) => {
      const target = questions.find((q) => q.id === id)
      const next = target ? !target.starred : false
      if (target) {
        setQuestions((prev) => prev.map((item) => (item.id === id ? { ...item, starred: next } : item)))
      }
      await api.toggleStar(id, next)
      // 同步收藏夹：收藏则置顶加入（默认组），取消则移出
      setFavorites((prev) => {
        if (next && target) {
          return prev.some((f) => f.id === id)
            ? prev.map((f) => (f.id === id ? { ...target, starred: true } : f))
            : [{ ...target, starred: true, favGroupId: 'default' }, ...prev]
        }
        return prev.filter((f) => f.id !== id)
      })
    },
    [questions],
  )

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]))
  }, [])

  const selectAll = useCallback((ids: string[]) => setSelectedIds(ids), [])
  const clearSelection = useCallback(() => setSelectedIds([]), [])

  /** 新建收藏分组：依次命名为未命名、未命名(1)、未命名(2)… */
  const addFavGroup = useCallback(() => {
    const names = new Set(favGroups.map((g) => g.name))
    let name = '未命名'
    let i = 0
    while (names.has(name)) {
      i += 1
      name = `未命名(${i})`
    }
    const group: FavoriteGroup = { id: `fg-${Date.now()}`, name }
    setFavGroups((prev) => [...prev, group])
    return group
  }, [favGroups])

  const renameFavGroup = useCallback((id: string, name: string) => {
    const trimmed = name.trim()
    if (!trimmed) return
    setFavGroups((prev) => prev.map((g) => (g.id === id ? { ...g, name: trimmed } : g)))
  }, [])

  /** 删除收藏分组：组内收藏题移入默认组，分组本身移除 */
  const removeFavGroup = useCallback((id: string) => {
    if (id === 'default') return
    setFavGroups((prev) => prev.filter((g) => g.id !== id))
    setFavorites((prev) => prev.map((f) => (f.favGroupId === id ? { ...f, favGroupId: 'default' } : f)))
  }, [])

  /** 点亮收藏：题目副本按分组写入收藏夹，全局星标同步点亮（含组卷记录中的题目快照） */
  const addToFavorites = useCallback((q: Question, groupId: string) => {
    const fav: Question = { ...q, starred: true, favGroupId: groupId }
    setQuestions((prev) => prev.map((item) => (item.id === q.id ? { ...item, starred: true } : item)))
    setFavorites((prev) => prev.some((f) => f.id === q.id) ? prev.map((f) => (f.id === q.id ? fav : f)) : [fav, ...prev])
    // 组卷记录的快照题目同步点亮，保证试卷详情页星标立即生效
    setRecords((prev) =>
      prev.map((r) =>
        r.questions?.some((x) => x.id === q.id)
          ? { ...r, questions: r.questions.map((x) => (x.id === q.id ? { ...x, starred: true } : x)) }
          : r,
      ),
    )
  }, [])

  /** 取消收藏：从收藏夹移除，全局题目与组卷快照的星标同步熄灭 */
  const unfavoriteQuestion = useCallback((questionId: string) => {
    setFavorites((prev) => prev.filter((f) => f.id !== questionId))
    setQuestions((prev) => prev.map((item) => (item.id === questionId ? { ...item, starred: false } : item)))
    setRecords((prev) =>
      prev.map((r) =>
        r.questions?.some((x) => x.id === questionId)
          ? { ...r, questions: r.questions.map((x) => (x.id === questionId ? { ...x, starred: false } : x)) }
          : r,
      ),
    )
  }, [])

  /** 已收藏题目更换分组 */
  const setFavoriteGroup = useCallback((questionId: string, groupId: string) => {
    setFavorites((prev) => prev.map((f) => (f.id === questionId ? { ...f, favGroupId: groupId } : f)))
  }, [])

  const publishPaper = useCallback(
    async (
      modules: PaperModule[],
      spaceIds: string[],
      saveRecord: boolean,
      name?: string,
      published = true,
      questions?: Question[],
      examWindow?: ExamWindow | null,
    ) => {
      // 发布必须选择学习空间；暂不发布（草稿）不要求
      if (published && !spaceIds.length) {
        showToast('请至少选择一个学习空间')
        return false
      }
      const record = await api.publishPaper({
        modules,
        // 记住组卷时调整后的题型模块顺序，讲解视图按此分区
        modulesOrder: modules,
        spaceIds,
        // 新建空间不在适配器静态演示表内，空间名称由前端解析后随载荷传入
        spaceNames: spaceIds
          .map((id) => spaces.find((s) => s.id === id)?.name ?? '')
          .filter(Boolean),
        saveRecord,
        name,
        published,
        // 按调整后的模块顺序重排题目，题号与讲解/作答视图分区保持一致
        questions: orderQuestionsByModules(questions, modules),
        examWindow,
      })
      if (record) setRecords((prev) => [record, ...prev])
      setSelectedIds([])
      showToast(
        published
          ? saveRecord
            ? '组卷已发布，并保存到组卷记录'
            : '组卷已发布到所选学习空间'
          : `试卷「${name ?? '未命名'}」已保存到组卷记录`,
      )
      return true
    },
    [spaces, showToast],
  )

  /** 删除一条组卷记录 */
  const deleteRecord = useCallback(
    async (id: string) => {
      setRecords((prev) => prev.filter((r) => r.id !== id))
      showToast('组卷记录已删除')
    },
    [showToast],
  )

  /** 从组卷记录的题目快照中删除若干题目 */
  const deleteRecordQuestions = useCallback((recordId: string, ids: string[]) => {
    setRecords((prev) =>
      prev.map((r) =>
        r.id === recordId
          ? {
              ...r,
              questions: (r.questions ?? []).filter((q) => !ids.includes(q.id)),
              questionCount: (r.questions ?? []).filter((q) => !ids.includes(q.id)).length,
            }
          : r,
      ),
    )
  }, [])

  /** 批量发布选中的组卷记录（仅对草稿生效） */
  const publishRecords = useCallback(
    (ids: string[]) => {
      let n = 0
      setRecords((prev) =>
        prev.map((r) => {
          if (!ids.includes(r.id) || r.published) return r
          n += 1
          return { ...r, published: true }
        }),
      )
      showToast(n ? `已发布 ${n} 份试卷` : '所选试卷均已发布')
    },
    [showToast],
  )

  /** 编辑模式保存组卷记录（命名/空间/做题时间/发布状态） */
  const updateRecord = useCallback(
    (record: AssembleRecord) => {
      setRecords((prev) => prev.map((r) => (r.id === record.id ? record : r)))
    },
    [],
  )

  /** 按编号加入空间：成员数与成员名单同步更新 */
  const joinSpaceByCode = useCallback(
    (code: string) => {
      const found = spaces.find((s) => s.code.toUpperCase() === code.trim().toUpperCase())
      if (!found) return null
      const displayName = profile.name
      setSpaces((prev) =>
        prev.map((s) =>
          s.id === found.id && !s.members.includes(displayName)
            ? { ...s, members: [...s.members, displayName], memberCount: Math.min(s.capacity, s.memberCount + 1) }
            : s,
        ),
      )
      showToast(`已加入学习空间「${found.name}」`)
      return found
    },
    [spaces, profile.name, showToast],
  )

  /** 学生退出空间：从列表移除，关联的组卷记录保留 */
  const leaveSpace = useCallback(
    (id: string) => {
      setSpaces((prev) => prev.filter((s) => s.id !== id))
      showToast('已退出学习空间')
    },
    [showToast],
  )

  /** 教师解散空间：空间整体移除，成员全部移出（演示态） */
  const dissolveSpace = useCallback(
    (id: string) => {
      setSpaces((prev) => prev.filter((s) => s.id !== id))
      showToast('学习空间已解散')
    },
    [showToast],
  )

  /** 从空间移出成员（人数同步） */
  const removeSpaceMember = useCallback((spaceId: string, name: string) => {
    setSpaces((prev) =>
      prev.map((s) =>
        s.id === spaceId && s.members.includes(name) && name !== s.creator
          ? { ...s, members: s.members.filter((m) => m !== name), memberCount: Math.max(0, s.memberCount - 1) }
          : s,
      ),
    )
  }, [])

  /** 重命名学习空间，并同步组卷记录中的空间名 */
  const renameSpace = useCallback((spaceId: string, newName: string) => {
    setSpaces((prev) => {
      const target = prev.find((s) => s.id === spaceId)
      if (!target || target.name === newName) return prev
      const old = target.name
      setRecords((rs) => rs.map((r) => ({ ...r, spaces: r.spaces.map((n) => (n === old ? newName : n)) })))
      return prev.map((s) => (s.id === spaceId ? { ...s, name: newName } : s))
    })
  }, [])

  /** 学生交卷 / 重新作答：同步更新组卷记录的作答状态 */
  const markRecordAnswered = useCallback((recordId: string, answered: boolean) => {
    setRecords((prev) => prev.map((r) => (r.id === recordId ? { ...r, answered } : r)))
  }, [])

  /** 跨页联动：请求打开某份试卷的查看标签（组卷记录页消费） */
  const [openPaperId, setOpenPaperId] = useState<string | null>(null)
  const requestOpenPaper = useCallback((recordId: string) => setOpenPaperId(recordId), [])
  const clearOpenPaper = useCallback(() => setOpenPaperId(null), [])

  /** 创建学习空间（编号自动生成，创建者为当前用户） */
  const createSpace = useCallback(
    (name: string, capacity: number) => {
      const code = `SP${new Date().getFullYear()}${Math.floor(Math.random() * 9000 + 1000)}`
      const space: StudySpace = {
        id: `sp-${Date.now()}`,
        name,
        code,
        memberCount: 1,
        capacity,
        creator: profile.name,
        members: [profile.name],
      }
      setSpaces((prev) => [...prev, space])
      showToast(`学习空间「${name}」创建成功`)
      return space
    },
    [profile.name, showToast],
  )

  /** 一键清空：题目、对话记录与对话记忆全部重置 */
  const clearAll = useCallback(() => {
    setQuestions([])
    setSelectedIds([])
    setMessages([])
    setInputDraft('')
    chatSlotState.current = {}
    setActiveTab('generate')
    showToast('已清空全部题目与对话记录')
  }, [showToast])

  /** 批量删除选中的题目 */
  const deleteSelected = useCallback(async () => {
    const ids = [...selectedIds]
    if (!ids.length) return
    await Promise.all(ids.map((id) => api.deleteQuestion(id)))
    setQuestions((prev) => prev.filter((q) => !ids.includes(q.id)))
    setFavorites((prev) => prev.filter((q) => !ids.includes(q.id)))
    setSelectedIds([])
    showToast(`已删除 ${ids.length} 道题目`)
  }, [selectedIds, showToast])

  /** 将文档拖入对话区上传并入库到当前知识库，成功后刷新文档列表 */
  const uploadDocument = useCallback(
    async (file: File) => {
      if (!selectedKbId) {
        showToast('请先在右侧选择知识库')
        return
      }
      const form = new FormData()
      form.append('file', file)
      form.append('kb_id', selectedKbId)
      showToast(`正在上传「${file.name}」…`)
      try {
        const resp = await fetch('/api/kb/upload', { method: 'POST', body: form })
        if (!resp.ok) {
          let detail: unknown = `HTTP ${resp.status}`
          try {
            detail = (await resp.json()).detail
          } catch {
            /* 保持默认 */
          }
          throw new Error(typeof detail === 'object' && detail !== null ? String((detail as { message?: string }).message) : String(detail))
        }
        const result = (await resp.json()) as { doc_id: string; doc_name: string }
        const docs = await api.listDocuments(selectedKbId)
        setDocs(docs)
        if (docs.some((d) => d.id === result.doc_id)) setSelectedDocId(result.doc_id)
        showToast(`「${result.doc_name}」已上传并入库`)
      } catch (err) {
        showToast(err instanceof Error ? err.message : '上传失败，请检查后端服务')
      }
    },
    [selectedKbId, showToast],
  )

  const value: AppState = {
    activeTab,
    setActiveTab,
    hasUnsavedChanges,
    setHasUnsavedChanges,
    settingsTarget,
    openEngineSettings,
    refreshKnowledgeBases,
    navCollapsed,
    toggleNav: () => setNavCollapsed((v) => !v),
    paramsCollapsed,
    toggleParams: () => setParamsCollapsed((v) => !v),
    kbs,
    docs,
    spaces,
    selectedKbId,
    selectedDocId,
    selectKb: (id) => void selectKb(id),
    selectDoc,
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
    updateProfile: (patch) => setProfile((prev) => ({ ...prev, ...patch })),
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
