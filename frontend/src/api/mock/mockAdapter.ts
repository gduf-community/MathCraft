import type { ApiClient, GenerateProgressHandler } from '../client'
import type {
  AssembleRecord,
  GenerateParams,
  PublishPayload,
  Question,
} from '../../types'
import { DEFAULT_SCORES, TYPE_LABELS } from '../../constants'
import { DOCUMENTS, KNOWLEDGE_BASES, QUESTION_BANK, STUDY_SPACES } from './mockData'
import { getBankDocsById, listAllBanks } from './bankMock'

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
    // 题库 id 不在内置文档清单时，回退到题库管理 mock 的文档数据
    const fromData = DOCUMENTS.filter((d) => d.kbId === kbId)
    if (fromData.length) return fromData
    return getBankDocsById(kbId).map((d) => ({ id: d.id, kbId, name: d.name }))
  },

  async listStudySpaces() {
    await delay(120)
    return STUDY_SPACES
  },

  async listAllBanks() {
    // 与题库管理同源联动：我创建的 + 我加入的全部题库
    await delay(120)
    return listAllBanks().map((b) => ({ id: b.id, name: b.name }))
  },

  async generateQuestions(params: GenerateParams, onProgress?: GenerateProgressHandler) {
    // 模拟与后端一致的阶段推进：检索 → 逐题型生成 → 校验，百分比反映 mock 生成各阶段
    const total = params.types.reduce((s, t) => s + t.count, 0) || 1
    const report = (percent: number, stage: string) => onProgress?.(Math.min(100, Math.round(percent)), stage)
    report(3, '任务已创建')
    await delay(260)
    report(6, '正在检索相关材料')
    await delay(320)
    const questions: Question[] = []
    const typeSpan = 84 / Math.max(1, params.types.length)
    for (let i = 0; i < params.types.length; i++) {
      const { type, count } = params.types[i]
      const base = 8 + i * typeSpan
      report(base, `正在生成${TYPE_LABELS[type] ?? '题目'}`)
      await delay(420)
      const bank = shuffle(QUESTION_BANK[type])
      for (let j = 0; j < count; j++) {
        const template = bank[j % bank.length]
        seq += 1
        const variant = j >= bank.length ? `（变式${Math.floor(j / bank.length) + 1}）` : ''
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
      report(base + typeSpan, `已生成 ${questions.length}/${total} 题`)
      await delay(140)
    }
    report(94, '正在校验题目格式与去重')
    await delay(240)
    report(100, '完成')
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
    const count = payload.modules.reduce((s, m) => s + m.count, 0)
    const total = payload.modules.reduce((s, m) => s + m.totalScore, 0)
    // 空间名称优先用调用方解析结果（新建空间不在静态演示表内），回退按 id 查表
    const spaceNames = payload.spaceNames.length
      ? payload.spaceNames
      : STUDY_SPACES.filter((s) => payload.spaceIds.includes(s.id)).map((s) => s.name)
    seq += 1
    const record: AssembleRecord = {
      id: `paper-${Date.now()}-${seq}`,
      name: payload.name || `试卷_${new Date().toLocaleDateString('zh-CN')}_${seq}`,
      createdAt: new Date().toLocaleString('zh-CN', { hour12: false }),
      questionCount: count,
      totalScore: total,
      spaces: spaceNames,
      published: payload.published !== false,
      questions: payload.questions ?? [],
      examWindow: payload.examWindow ?? null,
      // 发布时未勾选保存则不进组卷记录页，但记录必须存在，学习空间页据此展示试卷
      savedToRecords: payload.published === false ? true : payload.saveRecord,
    }
    return record
  },
}
