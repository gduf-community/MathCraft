/**
 * HTTP 适配器：调用 FastAPI 后端（vite dev 通过 /api 代理到 localhost:8000）。
 * 实现与 mockAdapter 相同的 ApiClient 接口，可随时切回 mock。
 * 题目与来源保存、读取和编辑接正式后端；收藏、组卷和学习空间保持演示状态。
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
import type { ApiClient, GenerateProgressHandler, UploadProgressHandler } from './client'
import { apiUrl } from './urls'

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
  const resp = await fetch(apiUrl(path), {
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

/** 对话出题：后端维护槽位状态机，questions 有值即表示本轮生成了题目 */
export interface ChatResult {
  reply: string
  slot_state: Record<string, unknown>
  questions: Question[]
  done: boolean
  error_type?: string | null
}

export function readSavedQuestion(id: string): Promise<Question> {
  return http<Question>(`/api/questions/${encodeURIComponent(id)}`)
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

async function waitForKnowledgeTask(taskId: string, onProgress?: UploadProgressHandler): Promise<void> {
  const resp = await fetch(apiUrl(`/api/knowledge-bases/tasks/${encodeURIComponent(taskId)}/stream`), {
    headers: { Accept: 'text/event-stream' },
  })
  if (!resp.ok) throw new Error(`任务跟踪失败：HTTP ${resp.status}`)
  if (!resp.body) throw new Error('任务跟踪失败：响应没有可读流')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventName = ''
  let dataLines: string[] = []
  const consume = (block: string): boolean => {
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
      else if (line === '') {
        if (!dataLines.length) continue
        let payload: { detail?: string; message?: string } = {}
        try {
          payload = JSON.parse(dataLines.join('\n')) as typeof payload
        } catch {
          throw new Error('任务跟踪失败：收到无效进度消息')
        }
        const detail = payload.detail || payload.message || ''
        if (eventName === 'failed') throw new Error(detail || '知识库处理失败')
        if (eventName === 'complete') {
          onProgress?.(100, detail || '处理完成')
          return true
        }
        eventName = ''
        dataLines = []
      }
    }
    return false
  }

  for (;;) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      if (consume(block)) {
        await reader.cancel()
        return
      }
    }
    if (done) break
  }
  throw new Error('知识库处理流提前结束')
}

export const httpAdapter: ApiClient = {
  async listSavedQuestions() { return http<Question[]>('/api/questions') },
  async listKnowledgeBases() {
    const bases = await http<Array<{ id?: string; name: string; available?: boolean; metadata?: { type?: string } | null }>>(
      '/api/knowledge-bases',
    )
    return bases
      .filter((base) => base.available !== false && !base.metadata?.type)
      .map<KnowledgeBase>((base) => ({ id: base.id || base.name, name: base.name }))
  },

  async listDocuments(kbId: string) {
    const result = await http<{ files: Array<{ name: string; type: string }> }>(
      `/api/knowledge-bases/${encodeURIComponent(kbId)}/files`,
    )
    let readiness: Array<{ document_key: string; status: string; warnings: string[] }>
    try {
      readiness = await http(`/api/knowledge-bases/${encodeURIComponent(kbId)}/document-readiness`)
    } catch (error) {
      return result.files.filter((file) => file.type === 'file').map<KbDocument>((file) => ({
        id: file.name, kbId, name: file.name, status: 'unavailable',
        warnings: [error instanceof Error ? error.message : '资料检查失败'],
      }))
    }
    return result.files
      .filter((file) => file.type === 'file')
      .map<KbDocument>((file) => {
        const state = readiness.find((d) => d.document_key === file.name)
        return { id: file.name, kbId, name: file.name, status: state?.status ?? 'unknown', warnings: state?.warnings }
      })
  },

  async uploadDocument(kbId: string, file: File, onProgress?: UploadProgressHandler) {
    const form = new FormData()
    form.append('files', file)
    const resp = await fetch(apiUrl(`/api/knowledge-bases/${encodeURIComponent(kbId)}/upload`), {
      method: 'POST',
      body: form,
    })
    if (!resp.ok) {
      let detail: unknown = `HTTP ${resp.status}`
      try {
        detail = (await resp.json()).detail
      } catch {
        /* 保持默认错误 */
      }
      throw new Error(
        typeof detail === 'object' && detail !== null
          ? String((detail as { message?: string }).message ?? detail)
          : String(detail),
      )
    }
    const result = (await resp.json()) as { task_id?: string }
    if (!result.task_id) {
      onProgress?.(100, '处理完成')
      return
    }
    onProgress?.(0, '已提交，后台处理中')
    await waitForKnowledgeTask(result.task_id, onProgress)
  },

  async listStudySpaces() {
    // 演示数据：与组卷弹窗、学习空间页同源联动
    return DEMO_SPACES.map((s) => ({ ...s, members: [...s.members] }))
  },

  async generateQuestions(params: GenerateParams, onProgress?: GenerateProgressHandler) {
    const body = JSON.stringify({
      // 题库即知识库：出题请求按所选题库 id 检索对应向量库 collection
      kb_id: params.kbId,
      doc_id: params.docId,
      types: params.types,
      difficulty: params.difficulty,
      source_mode: 'variant_data',
      scope: params.scope ?? '',
      existing_stems: params.existingStems ?? [],
    })
    onProgress?.(0, '已提交，正在生成')
    const result = await http<Question[]>('/api/generate', { method: 'POST', body })
    onProgress?.(100, '生成完成')
    return result
  },

  async updateQuestion(question: Question) {
    const { type, score, difficulty, stem, options, answer, analysis, knowledgePoint } = question
    return http<Question>(`/api/questions/${encodeURIComponent(question.id)}`, {
      method: 'PUT', body: JSON.stringify({ type, score, difficulty, stem, options, answer, analysis, knowledgePoint }),
    })
  },

  async deleteQuestion(_id: string) {
    /* 仅移出当前预览；持久化记录保留，重新加载仍可回查。 */
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
      examWindow: payload.examWindow ?? null,
      // 演示：随机生成已提交作答人数
      submittedCount: payload.published === false ? 0 : Math.floor(Math.random() * 20),
      // 发布时未勾选保存则不进组卷记录页，但记录必须存在，学习空间页据此展示试卷
      savedToRecords: payload.published === false ? true : payload.saveRecord,
    }
  },
}

export type { KnowledgeBase }
