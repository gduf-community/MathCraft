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
import { CURRENT_USER } from '../constants'
import defaultAvatar from '../assets/teacher_avatar.png'

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
  /** 生成进度：null=空闲；progressPercent 为当前阶段百分比 */
  genProgress: { progressPercent: number; stage: string } | null
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
  createSpace: (name: string, capacity: number) => StudySpace
  updateRecord: (record: AssembleRecord) => void
  dissolveSpace: (id: string) => void
  removeSpaceMember: (spaceId: string, name: string) => void
  renameSpace: (spaceId: string, newName: string) => void
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

export function AppProvider({ children }: { children: ReactNode }) {
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
    setKbs(await api.listKnowledgeBases())
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
  const [genProgress, setGenProgress] = useState<{ progressPercent: number; stage: string } | null>(null)

  const [questions, setQuestions] = useState<Question[]>([])
  const [favorites, setFavorites] = useState<Question[]>([])
  // 收藏分组：default 组固定存在，其余由用户在收藏页新建
  const [favGroups, setFavGroups] = useState<FavoriteGroup[]>([{ id: 'default', name: '默认' }])
  const [profile, setProfile] = useState<TeacherProfile>({
    name: CURRENT_USER,
    avatar: defaultAvatar,
    gender: '男',
    phone: '13800138000',
    email: 'zhang@163.com',
    teacherId: 'TK20240001',
    school: '广东金融学院',
    identity: '教师',
  })
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
      const [kbList, spaceList, savedQuestions] = await Promise.all([
        api.listKnowledgeBases(), api.listStudySpaces(), api.listSavedQuestions(),
      ])
      setKbs(kbList)
      setSpaces(spaceList)
      setQuestions(savedQuestions)
    })()
  }, [])

  const selectKb = useCallback(async (id: string) => {
    setSelectedKbId(id)
    setSelectedDocId('')
    setTypeConfigs(initialTypeConfigs)
    setDifficulty('中')
    setKnowledgeScope('')
    chatSlotState.current = {}
    setDocs(await api.listDocuments(id))
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
      setGenProgress({ progressPercent: 0, stage: '准备生成' })
      try {
        const list = await api.generateQuestions(
          {
            // 题库即知识库：把所选题库 id 传给后端检索对应 collection
            kbId: selectedKbId,
            docId: doc.id,
            docName: doc.name,
            difficulty,
            types,
            scope: knowledgeScope.trim() || undefined,
            // 全局去重：把当前已有题目题干传给后端
            existingStems: questions.map((q) => q.stem),
          },
          // 后端打点的真实进度：百分比 + 阶段文案
          (progressPercent, stage) => setGenProgress({ progressPercent, stage }),
        )
        setGenProgress(null)
        // 追加合并，不覆盖已出的题目（对话出题与参数出题共存）
        setQuestions((prev) => {
          const seenIds = new Set(prev.map((question) => question.id))
          const seenStems = new Set(prev.map((question) => question.stem.replace(/\s+/g, '')))
          const additions = list.filter((question) => {
            const stem = question.stem.replace(/\s+/g, '')
            if (seenIds.has(question.id) || seenStems.has(stem)) return false
            seenIds.add(question.id)
            seenStems.add(stem)
            return true
          })
          return [...prev, ...additions]
        })
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
    [docs, selectedDocId, selectedKbId, typeConfigs, difficulty, knowledgeScope, questions, showToast, setActiveTab],
  )

  const sendChat = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return
      // 出题必须绑定正式知识库中的具体文档
      if (!selectedKbId || !selectedDocId) {
        showToast('请先在右侧选择知识库文档，才能基于知识库出题')
        return
      }
      setMessages((prev) => [...prev, { id: `m-${Date.now()}`, role: 'user', text: trimmed }])
      setBotThinking(true)
      try {
        const configuredTypes = (Object.keys(typeConfigs) as QuestionType[])
          .filter((type) => typeConfigs[type].checked && typeConfigs[type].count > 0)
          .map((type) => ({ type, count: typeConfigs[type].count }))
        const slotState = Object.keys(chatSlotState.current).length
          ? chatSlotState.current
          : {
              ...(configuredTypes.length ? { types: configuredTypes } : {}),
              difficulty,
              ...(knowledgeScope.trim() ? { scope: knowledgeScope.trim() } : {}),
            }
        const res = await chat({
          kb_id: selectedKbId,
          doc_id: selectedDocId,
          message: trimmed,
          history: messages.slice(-6).map((m) => ({ role: m.role, text: m.text })),
          slot_state: slotState,
          // 全局去重：把当前已有题目题干传给后端
          existing_stems: questions.map((q) => q.stem),
        })
        chatSlotState.current = res.slot_state
        setMessages((prev) => [...prev, { id: `m-${Date.now()}-a`, role: 'assistant', text: res.reply }])
        if (res.questions?.length) {
          // 对话路径不强制切页：AI 回复先可见，题目已在「题目预览」标签页等候
          setQuestions((prev) => {
            const seenIds = new Set(prev.map((question) => question.id))
            const seenStems = new Set(prev.map((question) => question.stem.replace(/\s+/g, '')))
            const additions = res.questions.filter((question) => {
              const stem = question.stem.replace(/\s+/g, '')
              if (seenIds.has(question.id) || seenStems.has(stem)) return false
              seenIds.add(question.id)
              seenStems.add(stem)
              return true
            })
            return [...prev, ...additions]
          })
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
    [selectedDocId, selectedKbId, messages, questions, typeConfigs, difficulty, knowledgeScope, showToast],
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
      showToast('已移出本次预览，保存的题目和来源仍保留')
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
        spaceIds,
        // 新建空间不在适配器静态演示表内，空间名称由前端解析后随载荷传入
        spaceNames: spaceIds
          .map((id) => spaces.find((s) => s.id === id)?.name ?? '')
          .filter(Boolean),
        saveRecord,
        name,
        published,
        questions,
        examWindow,
      })
      if (record) setRecords((prev) => [record, ...prev])
      setSelectedIds([])
      showToast(
        published
          ? saveRecord
            ? '组卷已发布，并保存到组卷记录'
            : '组卷已发布到所选学习空间'
          : `试卷「${name ?? '未命名'}」已暂存为草稿`,
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

  /** 解散学习空间（关联的组卷记录保留） */
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
        creator: CURRENT_USER,
        members: [CURRENT_USER],
      }
      setSpaces((prev) => [...prev, space])
      showToast(`学习空间「${name}」创建成功`)
      return space
    },
    [showToast],
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
  }, [showToast, setActiveTab])

  /** 批量删除选中的题目 */
  const deleteSelected = useCallback(async () => {
    const ids = [...selectedIds]
    if (!ids.length) return
    await Promise.all(ids.map((id) => api.deleteQuestion(id)))
    setQuestions((prev) => prev.filter((q) => !ids.includes(q.id)))
    setFavorites((prev) => prev.filter((q) => !ids.includes(q.id)))
    setSelectedIds([])
    showToast(`已移出本次预览 ${ids.length} 道题目，保存记录仍保留`)
  }, [selectedIds, showToast])

  /** 将文档拖入对话区上传并入库到当前知识库，成功后刷新文档列表 */
  const uploadDocument = useCallback(
    async (file: File) => {
      if (!selectedKbId) {
        showToast('请先在右侧选择知识库')
        return
      }
      showToast(`已提交「${file.name}」，后台处理中…`)
      try {
        await api.uploadDocument(selectedKbId, file, (_progressPercent, stage) => {
          if (stage) showToast(`「${file.name}」${stage}`)
        })
        setDocs(await api.listDocuments(selectedKbId))
        showToast(`「${file.name}」已处理完成`)
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
    createSpace,
    updateRecord,
    dissolveSpace,
    removeSpaceMember,
    renameSpace,
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
