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
    folderId: 'f-probability',
    collectedAt: daysAgo(5),
    source: { bankName: '概率论与数理统计', chapter: '第四章 数字特征' },
    question: question(
      'Q-2409-0188',
      'compute',
      12,
      '高',
      '随机变量的数字特征',
      String.raw`设随机变量 $X_1,X_2,X_3$ 相互独立，且 $X_1\sim b(4,\dfrac12)$，$X_2\sim b(6,\dfrac13)$，
$X_3\sim b(6,\dfrac13)$。(1) 求 $P\{X_1=2,X_2=2,X_3=5\}$、$E(X_1X_2X_3)$、$E(X_1-X_2)$、
$E(X_1-2X_2)$；(2) 设 $X,Y$ 为随机变量，且 $E(X)=3$、$E(Y)=1$、$D(X)=4$、$D(Y)=9$，
令 $Z=5X-Y+15$，分别在下列 3 种情况下求 $E(Z)$ 和 $D(Z)$：
(i) $X,Y$ 相互独立；(ii) $X,Y$ 不相关；(iii) $X$ 与 $Y$ 的相关系数为 $0.25$。`,
      [],
      String.raw`(1) $P\{X_1=2,X_2=2,X_3=5\}=\dfrac{40}{19683}$，$E(X_1X_2X_3)=8$，$E(X_1-X_2)=0$，
$E(X_1-2X_2)=-2$；(2) $E(Z)=29$；(i) $D(Z)=109$；(ii) $D(Z)=109$；(iii) $D(Z)=94$。`,
      String.raw`$X_1\sim b(4,\frac12)$、$X_2\sim b(6,\frac13)$、$X_3\sim b(6,\frac13)$ 的期望均为 2。
(1) 由独立性 $P\{X_1=2,X_2=2,X_3=5\}=\binom42(\frac12)^4\cdot\binom62(\frac13)^2(\frac23)^4$
$\cdot\binom65(\frac13)^5(\frac23)=\frac{40}{19683}$；$E(X_1X_2X_3)=2\cdot2\cdot2=8$；
$E(X_1-X_2)=2-2=0$；$E(X_1-2X_2)=2-4=-2$。
(2) $E(Z)=5E(X)-E(Y)+15=29$；$D(Z)=25D(X)+D(Y)-10\mathrm{Cov}(X,Y)=109-10\mathrm{Cov}(X,Y)$。
(i)(ii) $\mathrm{Cov}(X,Y)=0$，故 $D(Z)=109$；
(iii) $\mathrm{Cov}(X,Y)=\rho\sqrt{D(X)D(Y)}=0.25\times6=1.5$，故 $D(Z)=109-15=94$。`,
      '概率论与数理统计',
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

/** 重排自建收藏夹；inbox 固定在最前，order 从 1 开始，仅会话内生效 */
export async function reorderFolders(orderedIds: string[]): Promise<void> {
  await delay(120)
  const byId = new Map(folders.map((folder) => [folder.id, folder]))
  const inbox = folders.find((folder) => folder.id === 'inbox')
  const next: FavoriteFolder[] = []
  for (const id of orderedIds) {
    const folder = byId.get(id)
    if (!folder || folder.id === 'inbox') continue
    next.push(folder)
  }
  next.forEach((folder, index) => {
    folder.order = index + 1
  })
  folders = inbox ? [{ ...inbox, order: 0 }, ...next] : next
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
