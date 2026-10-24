import type { ApiClient } from '../client'
import type {
  AssembleRecord,
  GenerateParams,
  PublishPayload,
  Question,
} from '../../types'
import { DEFAULT_SCORES } from '../../constants'
import { DOCUMENTS, KNOWLEDGE_BASES, QUESTION_BANK, STUDY_SPACES } from './mockData'

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

let seq = 0

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

/**
 * Mock 适配器：内存数据 + 模拟网络延迟。
 * 与真实后端唯一的差别是数据不落盘，接口签名与 client.ts 中定义完全一致。
 */
export const mockAdapter: ApiClient = {
  async listKnowledgeBases() {
    await delay(120)
    return KNOWLEDGE_BASES
  },

  async listDocuments(kbId: string) {
    await delay(120)
    return DOCUMENTS.filter((d) => d.kbId === kbId)
  },

  async listStudySpaces() {
    await delay(120)
    return STUDY_SPACES
  },

  async generateQuestions(params: GenerateParams) {
    await delay(600 + Math.random() * 500)
    const questions: Question[] = []
    for (const { type, count } of params.types) {
      const bank = shuffle(QUESTION_BANK[type])
      for (let i = 0; i < count; i++) {
        const template = bank[i % bank.length]
        seq += 1
        const variant = i >= bank.length ? `（变式${Math.floor(i / bank.length) + 1}）` : ''
        questions.push({
          id: `q-${Date.now()}-${seq}`,
          type,
          score: DEFAULT_SCORES[type],
          difficulty: params.difficulty,
          stem: template.stem + variant,
          options: template.options.map((o) => ({ ...o })),
          answer: template.answer,
          analysis: template.analysis,
          knowledgePoint: template.knowledgePoint,
          starred: false,
          docName: params.docName,
        })
      }
    }
    return questions
  },

  async updateQuestion(question: Question) {
    await delay(150)
    return { ...question }
  },

  async deleteQuestion(_id: string) {
    await delay(150)
  },

  async toggleStar(_id: string, _starred: boolean) {
    await delay(100)
  },

  async publishPaper(payload: PublishPayload) {
    await delay(500)
    if (!payload.saveRecord) return null
    const count = payload.modules.reduce((s, m) => s + m.count, 0)
    const total = payload.modules.reduce((s, m) => s + m.totalScore, 0)
    const spaceNames = STUDY_SPACES.filter((s) => payload.spaceIds.includes(s.id)).map((s) => s.name)
    seq += 1
    const record: AssembleRecord = {
      id: `paper-${Date.now()}-${seq}`,
      name: `试卷_${new Date().toLocaleDateString('zh-CN')}_${seq}`,
      createdAt: new Date().toLocaleString('zh-CN', { hour12: false }),
      questionCount: count,
      totalScore: total,
      spaces: spaceNames,
    }
    return record
  },
}
