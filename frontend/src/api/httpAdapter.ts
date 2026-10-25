/**
 * HTTP 适配器：调用 FastAPI 后端（开发时由 Vite 代理到 .env 配置的出题服务）。
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
import type { ApiClient } from './client'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE_URL}${path}`, {
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

export const httpAdapter: ApiClient = {
  async listKnowledgeBases() {
    const items = await http<{ id: string; name: string }[]>('/api/knowledge-bases')
    return items.map<KnowledgeBase>((item) => ({ id: item.id, name: item.name }))
  },

  async listDocuments(kbId: string) {
    const result = await http<{ files: { name: string; type: string }[] }>(
      `/api/knowledge-bases/${encodeURIComponent(kbId)}/files`,
    )
    return result.files
      .filter((file) => file.type === 'file')
      .map<KbDocument>((file) => ({ id: file.name, kbId, name: file.name }))
  },

  async listStudySpaces() {
    return [
      { id: 'sp-1', name: '24软工1班' },
      { id: 'sp-2', name: '25计科2班' },
      { id: 'sp-3', name: '24大数据1班' },
      { id: 'sp-4', name: '23计科1班' },
    ]
  },

  async generateQuestions(params: GenerateParams) {
    return http<Question[]>('/api/generate', {
      method: 'POST',
      body: JSON.stringify({
        kb_id: params.kbId,
        doc_id: params.docId,
        types: params.types,
        difficulty: params.difficulty,
        source_mode: 'variant_data',
        scope: params.scope ?? '',
        existing_stems: params.existingStems ?? [],
      }),
    })
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
    if (!payload.saveRecord) return null
    const spaces: StudySpace[] = [
      { id: 'sp-1', name: '24软工1班' },
      { id: 'sp-2', name: '25计科2班' },
      { id: 'sp-3', name: '24大数据1班' },
      { id: 'sp-4', name: '23计科1班' },
    ]
    const count = payload.modules.reduce((s: number, m: PaperModule) => s + m.count, 0)
    const total = payload.modules.reduce((s: number, m: PaperModule) => s + m.totalScore, 0)
    return {
      id: `paper-${Date.now()}`,
      name: `试卷_${new Date().toLocaleDateString('zh-CN')}`,
      createdAt: new Date().toLocaleString('zh-CN', { hour12: false }),
      questionCount: count,
      totalScore: total,
      spaces: spaces.filter((s) => payload.spaceIds.includes(s.id)).map((s) => s.name),
    }
  },
}

export type { KnowledgeBase }
