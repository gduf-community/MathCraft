import type { Difficulty, QuestionType } from './types'

export const TYPE_LABELS: Record<QuestionType, string> = {
  single: '选择题',
  multiple: '多选题',
  judge: '判断题',
  blank: '填空题',
  compute: '计算题',
  essay: '简答题',
}

/** 题型的固定排列顺序，组卷模块排序以此为基准 */
export const TYPE_ORDER: QuestionType[] = ['single', 'multiple', 'judge', 'blank', 'compute', 'essay']

export const DIFFICULTIES: Difficulty[] = ['低', '中', '高', '地狱']

/** 各题型的默认分值 */
export const DEFAULT_SCORES: Record<QuestionType, number> = {
  single: 5,
  multiple: 8,
  judge: 3,
  blank: 4,
  compute: 12,
  essay: 10,
}
