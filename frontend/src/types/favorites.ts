import type { Question } from './index'

/** 收藏题目来源：题库、文档与章节，仅用于收藏页展示 */
export interface FavoriteSource {
  bankName?: string
  docName?: string
  chapter?: string
}

/** 收藏关系：题目本身仍由 Question 承载 */
export interface FavoriteItem {
  id: string
  questionId: string
  /** 'inbox' 表示未分类 */
  folderId: string
  /** ISO 时间 */
  collectedAt: string
  source: FavoriteSource
  question: Question
}

/** 收藏夹；「全部收藏」是虚拟入口，不在此列表中 */
export interface FavoriteFolder {
  id: string
  name: string
  description?: string
  order: number
}
