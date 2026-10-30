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
 * 统一 FastAPI app 已提供的出题入口。
 * httpAdapter 适配后端字段；学习空间、编辑、收藏与组卷仍为本地演示，
 * 不为这些演示操作声明尚不存在的 HTTP 路由。
 */
export const ENDPOINTS = {
  knowledgeBases: '/api/knowledge-bases',
  documents: '/api/knowledge-bases/:kbId/files',
  generate: '/api/generate',
  chat: '/api/chat',
} as const

export interface ApiClient {
  listKnowledgeBases(): Promise<KnowledgeBase[]>
  listDocuments(kbId: string): Promise<KbDocument[]>
  listStudySpaces(): Promise<StudySpace[]>
  generateQuestions(params: GenerateParams): Promise<Question[]>
  updateQuestion(question: Question): Promise<Question>
  deleteQuestion(id: string): Promise<void>
  toggleStar(id: string, starred: boolean): Promise<void>
  publishPaper(payload: PublishPayload): Promise<AssembleRecord | null>
}

/**
 * 当前接入 FastAPI 后端（httpAdapter），开发时 Vite 将 /api 代理到根目录 .env 配置的出题服务。
 * 若要切回纯前端演示模式，把下面一行换回 mockAdapter 即可。
 */
import { httpAdapter } from './httpAdapter'

export const api: ApiClient = httpAdapter
