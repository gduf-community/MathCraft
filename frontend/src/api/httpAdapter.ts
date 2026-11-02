/**
 * HTTP 适配器：调用 FastAPI 后端（vite dev 通过 /api 代理到 localhost:8000）。
 * 实现与 mockAdapter 相同的 ApiClient 接口，可随时切回 mock。
 * 题目编辑/删除/收藏/组卷发布暂由前端本地状态维护，后端持久化后续补充。
 */
import type {
  AssembleRecord,
  GenerateParams,
  KbDocument,
  KnowledgeBase,
  PaperModule,
  PublishPayload,
  Question,
  StudySpace,
} from '../types'
import type { ApiClient, GenerateProgressHandler } from './client'
import { getBankDocsById, listAllBanks as listManagedBanks } from './mock/bankMock'

/** 生成空间成员名单（首项为创建者，其余为演示学生） */
const gen = (capacity: number, creator: string, count: number): string[] => [
  creator,
  ...Array.from({ length: Math.max(0, count - 1) }, (_, i) => `学生${i + 1}`),
]

/** 演示学习空间数据（列表 / 组卷弹窗 / 发布记录共用同一份，保证 id 一致） */
const DEMO_SPACES: StudySpace[] = [
  { id: 'sp-01', name: '24软工1班', code: 'SP20260001', memberCount: 24, capacity: 50, creator: '张老师', members: gen(50, '张老师', 24) },
  { id: 'sp-02', name: '25计科2班', code: 'SP20260002', memberCount: 31, capacity: 50, creator: '张老师', members: gen(50, '张老师', 31) },
  { id: 'sp-03', name: '24大数据1班', code: 'SP20260003', memberCount: 18, capacity: 50, creator: '张老师', members: gen(50, '张老师', 18) },
  { id: 'sp-04', name: '23计科1班', code: 'SP20260004', memberCount: 40, capacity: 50, creator: '李老师', members: gen(50, '李老师', 40) },
  { id: 'sp-05', name: '25软工2班', code: 'SP20260005', memberCount: 27, capacity: 50, creator: '王老师', members: gen(50, '王老师', 27) },
  { id: 'sp-06', name: '高数辅导小组', code: 'SP20260006', memberCount: 12, capacity: 30, creator: '李老师', members: gen(30, '李老师', 12) },
  { id: 'sp-07', name: '线性代数强化班', code: 'SP20260007', memberCount: 22, capacity: 40, creator: '张老师', members: gen(40, '张老师', 22) },
  { id: 'sp-08', name: '概率论研习社', code: 'SP20260008', memberCount: 15, capacity: 30, creator: '陈老师', members: gen(30, '陈老师', 15) },
  { id: 'sp-09', name: '离散数学讨论班', code: 'SP20260009', memberCount: 19, capacity: 35, creator: '王老师', members: gen(35, '王老师', 19) },
  { id: 'sp-10', name: '数据结构实训班', code: 'SP20260010', memberCount: 33, capacity: 45, creator: '张老师', members: gen(45, '张老师', 33) },
  { id: 'sp-11', name: '算法竞赛集训队', code: 'SP20260011', memberCount: 9, capacity: 20, creator: '刘老师', members: gen(20, '刘老师', 9) },
  { id: 'sp-12', name: '英语四六级备考群', code: 'SP20260012', memberCount: 45, capacity: 60, creator: '赵老师', members: gen(60, '赵老师', 45) },
  { id: 'sp-13', name: '大学物理实验班', code: 'SP20260013', memberCount: 26, capacity: 40, creator: '陈老师', members: gen(40, '陈老师', 26) },
  { id: 'sp-14', name: '考研数学冲刺班', code: 'SP20260014', memberCount: 38, capacity: 50, creator: '李老师', members: gen(50, '李老师', 38) },
  { id: 'sp-15', name: '软件工程毕设组', code: 'SP20260015', memberCount: 8, capacity: 15, creator: '张老师', members: gen(15, '张老师', 8) },
]

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    let detail: unknown = `HTTP ${resp.status}`
    try {
      detail = (await resp.json()).detail
    } catch {
      /* 保持默认信息 */
    }
    // 结构化错误（如原题数量不足确认）取 message 字段
    throw new Error(typeof detail === 'object' && detail !== null ? String((detail as { message?: string }).message) : String(detail))
  }
  return resp.json() as Promise<T>
}

/** 请求并容忍 404（后端未实现预留端点时由调用方回退） */
async function httpAllow404<T>(path: string, init?: RequestInit): Promise<T | null> {
  const resp = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (resp.status === 404) return null
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return (await resp.json()) as T
}

/** 对话出题：后端维护槽位状态机，questions 有值即表示本轮生成了题目 */
export interface ChatResult {
  reply: string
  slot_state: Record<string, unknown>
  questions: Question[]
  done: boolean
}

export function chat(body: {
  kb_id: string
  doc_id: string
  message: string
  history: { role: 'user' | 'assistant'; text: string }[]
  slot_state: Record<string, unknown>
  existing_stems: string[]
}): Promise<ChatResult> {
  return http<ChatResult>('/api/chat', { method: 'POST', body: JSON.stringify(body) })
}

interface GenerateTaskState {
  progress: number
  stage: string
  done: boolean
  questions: Question[] | null
  error: { kind?: string; message: string } | null
}

/** 轮询生成任务，把后端打点的真实进度透传给 onProgress；出错抛出结构化信息 */
async function pollGenerateTask(taskId: string, onProgress?: GenerateProgressHandler): Promise<Question[]> {
  for (;;) {
    const state = await http<GenerateTaskState>(`/api/generate/progress/${taskId}`)
    onProgress?.(state.progress, state.stage)
    if (state.done) {
      if (state.error) {
        throw new Error(state.error.message || '生成失败')
      }
      return state.questions ?? []
    }
    await new Promise((r) => setTimeout(r, 300))
  }
}

export const httpAdapter: ApiClient = {
  async listKnowledgeBases() {
    // 知识库实体暂为固定项，上传接口按 kb_id 建 collection
    return [{ id: 'kb-math', name: '高等数学知识库' }]
  },

  async listDocuments(kbId: string) {
    const docs = await http<{ doc_id: string; doc_name: string; chunks: number }[]>(
      `/api/kb/documents?kb_id=${encodeURIComponent(kbId)}`,
    ).catch(() => [] as { doc_id: string; doc_name: string; chunks: number }[])
    // 后端该题库尚未入库任何文档时，回退展示题库管理里的演示文档清单
    if (docs.length) {
      return docs.map<KbDocument>((d) => ({ id: d.doc_id, kbId, name: d.doc_name }))
    }
    return getBankDocsById(kbId).map<KbDocument>((d) => ({ id: d.id, kbId, name: d.name }))
  },

  async listStudySpaces() {
    // 演示数据：与组卷弹窗、学习空间页同源联动
    return DEMO_SPACES.map((s) => ({ ...s, members: [...s.members] }))
  },

  async listAllBanks() {
    // 题库管理联动：后端按 /api/banks 返回全部题库；未实现时回退到前端题库管理数据（我创建的 + 我加入的）
    const banks = await httpAllow404<{ id: string; name: string }[]>(`/api/banks`)
    if (banks?.length) return banks.map((b) => ({ id: b.id, name: b.name }))
    return listManagedBanks().map((b) => ({ id: b.id, name: b.name }))
  },

  async generateQuestions(params: GenerateParams, onProgress?: GenerateProgressHandler) {
    const body = JSON.stringify({
      // 题库即知识库：出题请求按所选题库 id 检索对应向量库 collection
      kb_id: params.kbId || 'kb-math',
      doc_id: params.docId,
      types: params.types,
      difficulty: params.difficulty,
      source_mode: 'variant_data',
      scope: params.scope ?? '',
      existing_stems: params.existingStems ?? [],
    })
    // 任务式生成：start 建任务，轮询 progress 拿后端打点的真实百分比；旧后端无 start 时回退同步端点
    try {
      const started = await httpAllow404<{ task_id: string }>('/api/generate/start', {
        method: 'POST',
        body,
      })
      if (started?.task_id) {
        return await pollGenerateTask(started.task_id, onProgress)
      }
    } catch (err) {
      // start/progress 链路异常（含 422 need_confirm）直接抛给上层
      throw err
    }
    // 回退：同步端点（无进度打点）
    return http<Question[]>('/api/generate', { method: 'POST', body })
  },

  async updateQuestion(question: Question) {
    // 后端持久化待接入：本地状态已即时生效
    return question
  },

  async deleteQuestion(_id: string) {
    /* 本地状态已即时生效 */
  },

  async toggleStar(_id: string, _starred: boolean) {
    /* 本地状态已即时生效 */
  },

  async publishPaper(payload: PublishPayload): Promise<AssembleRecord | null> {
    const count = payload.modules.reduce((s: number, m: PaperModule) => s + m.count, 0)
    const total = payload.modules.reduce((s: number, m: PaperModule) => s + m.totalScore, 0)
    // 空间名称优先用调用方解析结果（新建空间不在演示静态表内），回退按 id 查表
    const spaceNames = payload.spaceNames.length
      ? payload.spaceNames
      : DEMO_SPACES.filter((s) => payload.spaceIds.includes(s.id)).map((s) => s.name)
    return {
      id: `paper-${Date.now()}`,
      name: payload.name || `试卷_${new Date().toLocaleDateString('zh-CN')}`,
      createdAt: new Date().toLocaleString('zh-CN', { hour12: false }),
      questionCount: count,
      totalScore: total,
      spaces: spaceNames,
      published: payload.published !== false,
      questions: payload.questions ?? [],
      modulesOrder: payload.modulesOrder,
      examWindow: payload.examWindow ?? null,
      // 学生作答状态：新发布默认未作答
      answered: false,
      // 演示：已提交作答人数（3~19 人，保证讲解视图分布有数据可展示）
      submittedCount: payload.published === false ? 0 : Math.floor(Math.random() * 17) + 3,
      // 发布时未勾选保存则不进组卷记录页，但记录必须存在，学习空间页据此展示试卷
      savedToRecords: payload.published === false ? true : payload.saveRecord,
    }
  },
}

export type { KnowledgeBase }
