import type { PaperModule, Question, QuestionType } from '../types'

/**
 * 按组卷规定的题型模块顺序重排题目：
 * - 依次取出各模块题型的题目（保持组卷时的相对顺序），未出现在模块中的题型按原序追加
 * - 用于发布组卷时重新编排题目序号，保证讲解/作答视图的题号与模块顺序一致
 */
export function orderQuestionsByModules(list: Question[] | undefined, mods: PaperModule[] | undefined): Question[] {
  const source = list ?? []
  if (!source.length || !mods?.length) return source
  const used = new Set<number>()
  const out: Question[] = []
  for (const m of mods) {
    source.forEach((q, i) => {
      if (q.type === m.type && !used.has(i)) {
        used.add(i)
        out.push(q)
      }
    })
  }
  source.forEach((q, i) => {
    if (!used.has(i)) out.push(q)
  })
  return out
}

/** 按题目在数组中的顺序给题型分区（讲解视图侧边栏用），编号 = 全局序号 */
export function groupOrderedQuestions(ordered: Question[]): { type: QuestionType; items: { q: Question; no: number }[] }[] {
  const groups: { type: QuestionType; items: { q: Question; no: number }[] }[] = []
  ordered.forEach((q, i) => {
    let g = groups.find((x) => x.type === q.type)
    if (!g) {
      g = { type: q.type, items: [] }
      groups.push(g)
    }
    g.items.push({ q, no: i + 1 })
  })
  return groups
}
