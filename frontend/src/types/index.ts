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
  /** 收藏分组 id（仅收藏副本携带，缺省属于 default 组） */
  favGroupId?: string
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
  /** 空间编号（自动生成，只读） */
  code: string
  memberCount: number
  capacity: number
  /** 创建者姓名，用于区分「我创建的 / 我加入的」 */
  creator: string
  /** 空间成员名单（首项为创建者） */
  members: string[]
}

/** 做题时间窗口（不限时间时不传或为 null） */
export interface ExamWindow {
  start: string
  end: string
}

export interface GenerateParams {
  /** 题库（知识库）id，与后端向量库 collection 对应；缺省用内置 kb-math */
  kbId?: string
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
  /** 组卷时用户调整后的题型模块顺序快照，供讲解视图分区使用 */
  modulesOrder?: PaperModule[]
  spaceIds: string[]
  /** 发布目标空间名称（与 spaceIds 一一对应，由调用方解析传入） */
  spaceNames: string[]
  saveRecord: boolean
  /** 组卷命名（可选，缺省用日期） */
  name?: string
  /** false=暂不发布（存草稿） */
  published?: boolean
  /** 组卷题目快照，存入组卷记录供查看 */
  questions?: Question[]
  /** 做题时间窗口（不限时间时不传） */
  examWindow?: ExamWindow | null
}

export interface AssembleRecord {
  id: string
  name: string
  createdAt: string
  questionCount: number
  totalScore: number
  spaces: string[]
  /** 发布状态：发布 / 未发布（草稿） */
  published?: boolean
  /** 组卷时的题目快照，供组卷记录查看 */
  questions?: Question[]
  /** 做题时间窗口（不限时间时不传） */
  examWindow?: ExamWindow | null
  /** 已提交作答的人数 */
  submittedCount?: number
  /** 是否已停止作答（提前结束） */
  stopped?: boolean
  /** 最近一次催交时间（空间试卷视图，用于 24 小时冷却置灰） */
  lastUrgeAt?: string | null
  /** 交卷后的操作：是否允许查看答案与解析 / 是否允许修改答案重新提交 */
  allowReview?: boolean
  allowRetake?: boolean
  /** 是否保存到组卷记录；发布时未勾选保存则为 false，仅用于学习空间展示，不出现在组卷记录页 */
  savedToRecords?: boolean
  /** 组卷时的题型模块顺序快照（用户可调整），讲解视图按此分区 */
  modulesOrder?: PaperModule[]
  /** 学生作答状态：已交卷为 true；重新作答后回到 false（学生视角状态标签用） */
  answered?: boolean
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
}

/** 题目收藏分组（default 组固定存在，不可删除） */
export interface FavoriteGroup {
  id: string
  name: string
  /** 是否为默认分组 */
  isDefault?: boolean
}

/** 教师个人信息（个人中心展示与编辑） */
export interface TeacherProfile {
  name: string
  avatar: string
  gender: '' | '男' | '女'
  phone: string
  email: string
  teacherId: string
  school: string
  identity: string
}
