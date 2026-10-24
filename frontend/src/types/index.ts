/** 题型 */
export type QuestionType = 'single' | 'multiple' | 'judge' | 'blank' | 'compute' | 'essay'

/** 题目难度 */
export type Difficulty = '低' | '中' | '高' | '地狱'

export interface OptionItem {
  label: string
  /** 选项内容，内联 LaTeX 用 $...$ 包裹 */
  text: string
}

export interface Question {
  id: string
  type: QuestionType
  /** 分值 */
  score: number
  difficulty: Difficulty
  /** 题干，内联 LaTeX 用 $...$ 包裹 */
  stem: string
  /** 客观题选项；主观题为空数组 */
  options: OptionItem[]
  /** 参考答案，可为 LaTeX 源码 */
  answer: string
  /** 答案解析，可为 LaTeX 源码 */
  analysis: string
  knowledgePoint: string
  starred: boolean
  /** 生成时使用的文档名 */
  docName: string
}

export interface KnowledgeBase {
  id: string
  name: string
}

export interface KbDocument {
  id: string
  kbId: string
  name: string
}

export interface StudySpace {
  id: string
  name: string
}

export interface GenerateParams {
  docId: string
  docName: string
  difficulty: Difficulty
  types: { type: QuestionType; count: number }[]
  /** 知识点或章节范围（可选） */
  scope?: string
  /** 已有题干，用于跨请求去重 */
  existingStems?: string[]
}

export interface PaperModule {
  type: QuestionType
  count: number
  totalScore: number
}

export interface PublishPayload {
  modules: PaperModule[]
  spaceIds: string[]
  saveRecord: boolean
}

export interface AssembleRecord {
  id: string
  name: string
  createdAt: string
  questionCount: number
  totalScore: number
  spaces: string[]
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
}
