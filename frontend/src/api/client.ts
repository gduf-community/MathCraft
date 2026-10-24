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
  question: '/api/questions/:id',
  publish: '/api/papers/publish',
  spaces: '/api/study-spaces',
  records: '/api/assemble-records',
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
 * 当前接入 FastAPI 后端（httpAdapter），开发时 vite 将 /api 代理到 localhost:8000。
 * 若要切回纯前端演示模式，把下面一行换回 mockAdapter 即可。
 */
import { httpAdapter } from './httpAdapter'

export const api: ApiClient = httpAdapter
