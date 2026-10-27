/**
 * 题目收藏 mock 层：数据与操作全部收敛在此，页面组件不硬编码任何数据。
 * 内存态 + 模拟网络延迟；刷新页面即恢复初始数据。
 * 后端接入时以同签名的 HTTP 实现替换本模块即可。
 */
import type { Question } from '../../types'
import type { FavoriteFolder, FavoriteItem, FavoriteSource } from '../../types/favorites'

const DAY = 86_400_000
const NOW = Date.now()
const daysAgo = (days: number) => new Date(NOW - days * DAY).toISOString()
const delay = (ms = 120) => new Promise<void>((resolve) => setTimeout(resolve, ms))
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T

let seq = 0
const uid = (prefix: string) => `${prefix}-${Date.now()}-${++seq}`

const option = (label: string, text: string) => ({ label, text })

const question = (
  id: string,
  type: Question['type'],
  score: number,
  difficulty: Question['difficulty'],
  knowledgePoint: string,
  stem: string,
  options: Question['options'],
  answer: string,
  analysis: string,
  docName: string,
): Question => ({
  id,
  type,
  score,
  difficulty,
  stem,
  options,
  answer,
  analysis,
  knowledgePoint,
  starred: true,
  docName,
})

let folders: FavoriteFolder[] = [
  { id: 'inbox', name: '未分类', description: '还没有归类的收藏', order: 0 },
  { id: 'f-derivative', name: '导数与微分', description: '第二章、第三章的导数与应用', order: 1 },
  { id: 'f-linear', name: '线性代数', description: '矩阵、行列式与线性方程组', order: 2 },
  { id: 'f-probability', name: '概率统计', description: '随机事件、概率计算与统计初步', order: 3 },
]

let items: FavoriteItem[] = [
  {
    id: 'fav-001',
    questionId: 'Q-2410-0132',
    folderId: 'f-linear',
    collectedAt: daysAgo(1),
    source: { bankName: '2024级高等代数', chapter: '第三章 矩阵' },
    question: question(
      'Q-2410-0132',
      'multiple',
      8,
      '中',
      '逆矩阵',
      '设 $A$、$B$ 为 $n$ 阶可逆矩阵，则下列结论正确的是（　）',
      [
        option('A', '$(AB)^{-1}=B^{-1}A^{-1}$'),
        option('B', '$(A+B)^{-1}=A^{-1}+B^{-1}$'),
        option('C', '$|AB|=|A||B|$'),
        option('D', '$(A^{T})^{-1}=(A^{-1})^{T}$'),
      ],
      'ACD',
      '由反序律 $(AB)^{-1}=B^{-1}A^{-1}$ 知 A 正确；矩阵加法与求逆不可交换，B 错误；同阶方阵满足 $|AB|=|A||B|$，C 正确；转置与求逆可交换，D 正确。',
      '2024级高等代数',
    ),
  },
  {
    id: 'fav-002',
    questionId: 'Q-2410-0128',
    folderId: 'f-derivative',
    collectedAt: daysAgo(2),
    source: { bankName: '高数基础题库', chapter: '第二章 导数与微分' },
    question: question(
      'Q-2410-0128',
      'single',
      5,
      '高',
      '切线方程',
      '曲线 $y=x^{3}-2x+1$ 在点 $(1,0)$ 处的切线方程为（　）',
      [
        option('A', '$y=x-1$'),
        option('B', '$y=x+1$'),
        option('C', '$y=-x+1$'),
        option('D', '$y=2x-2$'),
      ],
      'A',
      '由 $y\\prime=3x^{2}-2$ 得斜率 $k=y\\prime(1)=1$，切线过点 $(1,0)$，故 $y=x-1$。',
      '高数基础题库',
    ),
  },
  {
    id: 'fav-003',
    questionId: 'Q-2410-0117',
    folderId: 'f-derivative',
    collectedAt: daysAgo(3),
    source: { bankName: '高数基础题库', chapter: '第二章 导数与微分' },
    question: question(
      'Q-2410-0117',
      'single',
      5,
      '低',
      '导数的应用',
      '函数 $f(x)=x^{3}-3x$ 在区间 $[-2,2]$ 上的最大值为（　）',
      [option('A', '2'), option('B', '−2'), option('C', '0'), option('D', '4')],
      'A',
      '$f\\prime(x)=3x^{2}-3$，令 $f\\prime(x)=0$ 得 $x=\\pm1$。比较 $f(-2)=-2$，$f(-1)=2$，$f(1)=-2$，$f(2)=2$，故最大值为 2。',
      '高数基础题库',
    ),
  },
  {
    id: 'fav-004',
    questionId: 'Q-2409-0206',
    folderId: 'f-probability',
    collectedAt: daysAgo(5),
    source: { bankName: '概率论与数理统计', chapter: '第一章 随机事件与概率' },
    question: question(
      'Q-2409-0206',
      'judge',
      3,
      '低',
      '独立性',
      '若事件 $A$ 与 $B$ 相互独立，则 $P(AB)=P(A)P(B)$。（　）',
      [],
      '正确（√）',
      '相互独立的定义即为 $P(AB)=P(A)P(B)$，反之在 $P(A)>0$ 时也成立。',
      '概率论与数理统计',
    ),
  },
  {
    id: 'fav-005',
    questionId: 'Q-2409-0188',
    folderId: 'f-derivative',
    collectedAt: daysAgo(6),
    source: { bankName: '高数基础题库', chapter: '第三章 微分中值定理' },
    question: question(
      'Q-2409-0188',
      'compute',
      12,
      '中',
      '极值与最值',
      '求函数 $f(x)=x^{3}-3x^{2}+2$ 的极值。',
      [],
      '极大值 $f(0)=2$，极小值 $f(2)=-2$',
      '$f\\prime(x)=3x^{2}-6x=3x(x-2)$。$x<0$ 时递增，$0<x<2$ 时递减，$x>2$ 时递增，故 $x=0$ 取极大值 2，$x=2$ 取极小值 $-2$。',
      '高数基础题库',
    ),
  },
  {
    id: 'fav-006',
    questionId: 'Q-2409-0154',
    folderId: 'f-derivative',
    collectedAt: daysAgo(9),
    source: { bankName: '高数基础题库', chapter: '第二章 导数与微分' },
    question: question(
      'Q-2409-0154',
      'judge',
      3,
      '低',
      '可导与连续',
      '若函数 $f(x)$ 在点 $x_{0}$ 处可导，则 $f(x)$ 在 $x_{0}$ 处连续。（　）',
      [],
      '正确（√）',
      '可导必连续，反之不成立，典型反例为 $f(x)=|x|$ 在 $x=0$ 处连续但不可导。',
      '高数基础题库',
    ),
  },
  {
    id: 'fav-007',
    questionId: 'Q-2409-0142',
    folderId: 'f-linear',
    collectedAt: daysAgo(12),
    source: { bankName: '2025级线性代数', chapter: '第二章 行列式' },
    question: question(
      'Q-2409-0142',
      'blank',
      4,
      '中',
      '行列式',
      '设 $A$ 为 3 阶方阵，$|A|=2$，则 $|2A|=$ ______。',
      [],
      '16',
      '由 $|kA|=k^{n}|A|$，取 $n=3$、$k=2$，得 $8\\times2=16$。',
      '2025级线性代数',
    ),
  },
  {
    id: 'fav-008',
    questionId: 'Q-2409-0121',
    folderId: 'f-derivative',
    collectedAt: daysAgo(15),
    source: { bankName: '高数基础题库', chapter: '第三章 微分中值定理' },
    question: question(
      'Q-2409-0121',
      'compute',
      12,
      '高',
      '单调性',
      '已知函数 $f(x)=\\ln x-ax$（$a\\in\\mathbb{R}$）。(1) 讨论 $f(x)$ 的单调性；(2) 若 $f(x)\\le 0$ 恒成立，求 $a$ 的取值范围。',
      [],
      '(1) $a\\le0$ 时在 $(0,+\\infty)$ 单调递增，$a>0$ 时在 $(0,\\frac{1}{a})$ 递增、在 $(\\frac{1}{a},+\\infty)$ 递减；(2) $a\\ge\\frac{1}{e}$',
      '定义域 $(0,+\\infty)$，$f\\prime(x)=\\frac{1}{x}-a$。当 $a>0$ 时最大值 $f(\\frac{1}{a})=-\\ln a-1$，令其 $\\le0$ 得 $a\\ge\\frac{1}{e}$。',
      '高数基础题库',
    ),
  },
  {
    id: 'fav-009',
    questionId: 'Q-2408-0098',
    folderId: 'f-probability',
    collectedAt: daysAgo(21),
    source: { bankName: '概率论与数理统计', chapter: '第三章 概率计算' },
    question: question(
      'Q-2408-0098',
      'essay',
      10,
      '高',
      '古典概型',
      '某班级有 5 名男生和 3 名女生，随机选出 3 人参加竞赛，求选出的 3 人中恰有 2 名女生的概率。',
      [],
      '$\\frac{15}{56}$',
      '基本事件总数 $C_{8}^{3}=56$，符合条件的事件数为 $C_{5}^{1}C_{3}^{2}=15$，故概率为 $\\frac{15}{56}$。',
      '概率论与数理统计',
    ),
  },
  {
    id: 'fav-010',
    questionId: 'Q-2408-0071',
    folderId: 'inbox',
    collectedAt: daysAgo(40),
    source: { bankName: '高数基础题库', chapter: '第一章 函数与极限' },
    question: question(
      'Q-2408-0071',
      'single',
      5,
      '中',
      '函数极限',
      '极限 $\\lim\\limits_{x\\to0}\\frac{\\sin 3x}{x}=$（　）',
      [option('A', '0'), option('B', '1'), option('C', '3'), option('D', '不存在')],
      'C',
      '由等价无穷小 $\\sin 3x\\sim3x$（$x\\to0$），得极限为 3。',
      '高数基础题库',
    ),
  },
]

export async function listFavorites(): Promise<FavoriteItem[]> {
  await delay()
  return clone(items)
}

export async function listFolders(): Promise<FavoriteFolder[]> {
  await delay()
  return clone(folders)
}

/** 收藏一道题；同一题重复收藏时返回既有记录（幂等） */
export async function addFavorite(
  target: Question,
  folderId = 'inbox',
  source: FavoriteSource = {},
): Promise<FavoriteItem> {
  await delay(100)
  const existing = items.find((item) => item.questionId === target.id)
  if (existing) return clone(existing)
  const next: FavoriteItem = {
    id: uid('fav'),
    questionId: target.id,
    folderId: folders.some((folder) => folder.id === folderId) ? folderId : 'inbox',
    collectedAt: new Date().toISOString(),
    source,
    question: { ...clone(target), starred: true },
  }
  items = [next, ...items]
  return clone(next)
}

export async function removeFavorite(id: string): Promise<FavoriteItem | null> {
  await delay(100)
  const index = items.findIndex((item) => item.id === id)
  if (index < 0) return null
  const [removed] = items.splice(index, 1)
  return clone(removed)
}

export async function restoreFavorite(item: FavoriteItem): Promise<void> {
  await delay(60)
  if (items.some((current) => current.id === item.id || current.questionId === item.questionId)) return
  items = [...items, clone(item)].sort((a, b) => b.collectedAt.localeCompare(a.collectedAt))
}

export async function createFolder(name: string, description = ''): Promise<FavoriteFolder> {
  await delay(120)
  const clean = name.trim()
  if (!clean) throw new Error('请填写收藏夹名称')
  if (folders.some((folder) => folder.name === clean)) throw new Error('已存在同名收藏夹')
  const folder: FavoriteFolder = {
    id: uid('fld'),
    name: clean,
    description: description.trim() || undefined,
    order: Math.max(0, ...folders.map((item) => item.order)) + 1,
  }
  folders = [...folders, folder]
  return clone(folder)
}

export async function renameFolder(id: string, name: string, description = ''): Promise<void> {
  await delay(100)
  const folder = folders.find((item) => item.id === id)
  if (!folder) throw new Error('收藏夹不存在')
  if (id === 'inbox') throw new Error('未分类不能重命名')
  const clean = name.trim()
  if (!clean) throw new Error('请填写收藏夹名称')
  if (folders.some((item) => item.id !== id && item.name === clean)) throw new Error('已存在同名收藏夹')
  folder.name = clean
  folder.description = description.trim() || undefined
}

/** 删除收藏夹时题目回流「未分类」，不删除题目 */
export async function deleteFolder(id: string): Promise<void> {
  await delay(100)
  if (id === 'inbox') throw new Error('未分类不能删除')
  if (!folders.some((item) => item.id === id)) throw new Error('收藏夹不存在')
  folders = folders.filter((item) => item.id !== id)
  items = items.map((item) => (item.folderId === id ? { ...item, folderId: 'inbox' } : item))
}

export async function moveFavorites(ids: string[], folderId: string): Promise<void> {
  await delay(100)
  if (!folders.some((folder) => folder.id === folderId)) throw new Error('收藏夹不存在')
  const target = new Set(ids)
  items = items.map((item) => (target.has(item.id) ? { ...item, folderId } : item))
}

/** 预览页编辑题目后同步收藏快照 */
export async function updateFavoriteQuestion(target: Question): Promise<void> {
  const index = items.findIndex((item) => item.questionId === target.id)
  if (index < 0) return
  items[index] = {
    ...items[index],
    question: { ...clone(target), starred: true },
  }
}
