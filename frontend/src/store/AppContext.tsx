import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api/client'
import { chat } from '../api/httpAdapter'
import type {
  AssembleRecord,
  ChatMessage,
  Difficulty,
  KbDocument,
  KnowledgeBase,
  PaperModule,
  Question,
  QuestionType,
  StudySpace,
} from '../types'

export type TabKey = 'generate' | 'preview'

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
  generate: (opts?: { silent?: boolean }) => Promise<boolean>

  // 题目与筛选
  questions: Question[]
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
  publishPaper: (modules: PaperModule[], spaceIds: string[], saveRecord: boolean) => Promise<boolean>

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

  const [questions, setQuestions] = useState<Question[]>([])
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

  // 初始化：加载知识库、文档与学习空间
  useEffect(() => {
    void (async () => {
      const [kbList, spaceList] = await Promise.all([api.listKnowledgeBases(), api.listStudySpaces()])
      setKbs(kbList)
      setSpaces(spaceList)
      if (kbList.length) {
        setSelectedKbId(kbList[0].id)
        const docs = await api.listDocuments(kbList[0].id)
        setDocs(docs)
        if (docs.length) setSelectedDocId(docs[0].id)
      }
    })()
  }, [])

  const selectKb = useCallback(async (id: string) => {
    setSelectedKbId(id)
    setSelectedDocId('')
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
      try {
        const list = await api.generateQuestions({
          docId: doc.id,
          docName: doc.name,
          difficulty,
          types,
          scope: knowledgeScope.trim() || undefined,
          // 全局去重：把当前已有题目题干传给后端
          existingStems: questions.map((q) => q.stem),
        })
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
          kb_id: 'kb-math',
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
    [selectedDocId, messages, questions, showToast],
  )

  const updateQuestion = useCallback(
    async (q: Question) => {
      const saved = await api.updateQuestion(q)
      setQuestions((prev) => prev.map((item) => (item.id === saved.id ? saved : item)))
      showToast('修改已保存')
    },
    [showToast],
  )

  const deleteQuestion = useCallback(
    async (id: string) => {
      await api.deleteQuestion(id)
      setQuestions((prev) => prev.filter((item) => item.id !== id))
      setSelectedIds((prev) => prev.filter((v) => v !== id))
      showToast('已删除该题')
    },
    [showToast],
  )

  const toggleStar = useCallback(async (id: string) => {
    let next = false
    setQuestions((prev) =>
      prev.map((item) => {
        if (item.id !== id) return item
        next = !item.starred
        return { ...item, starred: next }
      }),
    )
    await api.toggleStar(id, next)
  }, [])

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]))
  }, [])

  const selectAll = useCallback((ids: string[]) => setSelectedIds(ids), [])
  const clearSelection = useCallback(() => setSelectedIds([]), [])

  const publishPaper = useCallback(
    async (modules: PaperModule[], spaceIds: string[], saveRecord: boolean) => {
      if (!spaceIds.length) {
        showToast('请至少选择一个学习空间')
        return false
      }
      const record = await api.publishPaper({ modules, spaceIds, saveRecord })
      if (record) setRecords((prev) => [record, ...prev])
      setSelectedIds([])
      showToast(saveRecord ? '组卷已发布，并保存到组卷记录' : '组卷已发布到所选学习空间')
      return true
    },
    [showToast],
  )

  const value: AppState = {
    activeTab,
    setActiveTab,
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
    generate: runGenerate,
    questions,
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
