import type {
  AssembleRecord,
  GenerateParams,
  KbDocument,
  KnowledgeBase,
  PublishPayload,
  Question,
  StudySpace,
} from '../types'

/** 生成进度回调：进度百分比与阶段文案。 */
export type GenerateProgressHandler = (progressPercent: number, stage: string) => void

/** 知识库后台任务回调：进度百分比与阶段文案。 */
export type UploadProgressHandler = (progressPercent: number, stage: string) => void

export interface ApiClient {
  listKnowledgeBases(): Promise<KnowledgeBase[]>
  listDocuments(kbId: string): Promise<KbDocument[]>
  uploadDocument(kbId: string, file: File, onProgress?: UploadProgressHandler): Promise<void>
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
