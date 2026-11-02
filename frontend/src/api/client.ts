import type {
  AssembleRecord,
  GenerateParams,
  KbDocument,
  KnowledgeBase,
  PublishPayload,
  Question,
  StudySpace,
} from '../types'

/**
 * 后端 API 端点预留。
 * 接入真实后端时，按此清单实现 httpAdapter 并在文件末尾替换默认导出即可，
 * 页面组件不需要任何改动。
 */
export const ENDPOINTS = {
  knowledgeBases: '/api/knowledge-bases',
  documents: '/api/knowledge-bases/:kbId/documents',
  generate: '/api/questions/generate',
  generateStart: '/api/generate/start',
  generateProgress: '/api/generate/progress/:taskId',
  question: '/api/questions/:id',
  publish: '/api/papers/publish',
  spaces: '/api/study-spaces',
  records: '/api/assemble-records',
  /** 题库管理联动的全部题库（我创建的 + 我加入的），用于知识库下拉 */
  banks: '/api/banks',
} as const

/** 生成进度回调：percent 为后端打点的真实百分比，stage 为阶段文案 */
export type GenerateProgressHandler = (percent: number, stage: string) => void

export interface ApiClient {
  listKnowledgeBases(): Promise<KnowledgeBase[]>
  /** 题库管理联动：我创建的 + 我加入的全部题库（与题库管理 mock/后端同源） */
  listAllBanks(): Promise<KnowledgeBase[]>
  listDocuments(kbId: string): Promise<KbDocument[]>
  listStudySpaces(): Promise<StudySpace[]>
  generateQuestions(params: GenerateParams, onProgress?: GenerateProgressHandler): Promise<Question[]>
  updateQuestion(question: Question): Promise<Question>
  deleteQuestion(id: string): Promise<void>
  toggleStar(id: string, starred: boolean): Promise<void>
  publishPaper(payload: PublishPayload): Promise<AssembleRecord | null>
}

/**
 * 当前接入 FastAPI 后端（httpAdapter），开发时 vite 将 /api 代理到 localhost:8000。
 * 若要切回纯前端演示模式，把下面一行换回 mockAdapter 即可。
 */
import { httpAdapter } from './httpAdapter'

export const api: ApiClient = httpAdapter
