/**
 * 题库管理 mock 层：数据与操作全部收敛在此，页面组件不硬编码任何数据。
 * 内存态 + 模拟网络延迟；后端接入时以 http 实现替换本模块即可（签名一致）。
 *
 * 权限模型（两级管理员）：
 * - 普通管理员：可上传和下载文档
 * - 超级管理员：可编辑文档（包括删除、上传、下载和查看）
 * 创建者恒为超级管理员；题库级 adminLevel 决定其余管理员的级别。
 */

export type AdminLevel = 'normal' | 'super'

export interface BankDoc {
  id: string
  name: string
  /** 展示用格式徽标：PDF / DOCX / XLSX / MD */
  format: string
  size: string
}

export interface BankMember {
  id: string
  name: string
  isAdmin: boolean
}

export interface ManagedBank {
  id: string
  name: string
  code: string
  memberCount: number
  capacity: number
  creator: string
  docs: BankDoc[]
  members: BankMember[]
  /** 管理员权限级别：normal=普通管理员（上传/下载） super=超级管理员（可编辑，含删除/上传/下载/查看） */
  adminLevel: AdminLevel
  /** 我加入的题库：当前用户是否已退出（退出后按钮置灰） */
  quitted?: boolean
}

const delay = (ms = 180) => new Promise((r) => setTimeout(r, ms))
const uid = (p: string) => `${p}-${Math.random().toString(36).slice(2, 8)}`

/** 当前登录用户（演示身份：张老师） */
export const CURRENT_USER = '张老师'

function member(name: string, isAdmin = false): BankMember {
  return { id: uid('m'), name, isAdmin }
}

function makeBank(
  name: string,
  code: string,
  memberCount: number,
  creator: string,
  docs: [string, string, string][],
  members: string[],
  meAdmin: boolean,
  adminLevel: AdminLevel = 'normal',
): ManagedBank {
  return {
    id: uid('bank'),
    name,
    code,
    memberCount,
    capacity: 200,
    creator,
    docs: docs.map(([n, f, s]) => ({ id: uid('d'), name: n, format: f, size: s })),
    members: members.map((m) => member(m, m === creator || (meAdmin && m === CURRENT_USER))),
    adminLevel,
  }
}

/** 我创建的题库（当前用户为创建者=超级管理员） */
const ownedBanks: ManagedBank[] = [
  makeBank('2024级高等代数', 'TK20240001', 1, CURRENT_USER,
    [['高等代数第一章讲义.pdf', 'PDF', '2.4 MB'], ['线性空间习题集.docx', 'DOCX', '368 KB'], ['章节知识点梳理.md', 'MD', '42 KB']],
    [CURRENT_USER, '李老师', '王老师'], true, 'super'),
  makeBank('2025级线性代数', 'TK20250002', 1, CURRENT_USER,
    [['矩阵运算基础.pdf', 'PDF', '1.8 MB'], ['行列式专项练习.xlsx', 'XLSX', '126 KB']],
    [CURRENT_USER, '赵老师'], true, 'normal'),
  makeBank('高数基础题库', 'TK20240003', 1, CURRENT_USER,
    [['极限与连续.pdf', 'PDF', '3.1 MB'], ['导数应用50题.docx', 'DOCX', '522 KB'], ['公式速查表.md', 'MD', '18 KB'], ['期末模拟卷.xlsx', 'XLSX', '204 KB']],
    [CURRENT_USER, '陈老师', '刘老师'], true, 'super'),
  makeBank('概率论与数理统计', 'TK20240004', 1, CURRENT_USER,
    [['随机变量分布.pdf', 'PDF', '2.2 MB'], ['数理统计习题.docx', 'DOCX', '410 KB']],
    [CURRENT_USER, '王老师'], true, 'super'),
  makeBank('大学物理（力学）', 'TK20240005', 1, CURRENT_USER,
    [['牛顿定律专题.pdf', 'PDF', '2.9 MB']],
    [CURRENT_USER, '李老师'], true, 'normal'),
  makeBank('高等数学综合练习', 'TK20240006', 1, CURRENT_USER,
    [['综合模拟卷一.pdf', 'PDF', '1.5 MB'], ['综合模拟卷二.pdf', 'PDF', '1.6 MB']],
    [CURRENT_USER], true, 'super'),
]

/** 我加入的题库（「高数基础题库」当前用户为超级管理员，用于演示权限门控） */
const joinedBanks: ManagedBank[] = [
  makeBank('2024级高等代数', 'TK20240001', 1, '李老师',
    [['高等代数课件.pdf', 'PDF', '4.2 MB']], ['李老师', CURRENT_USER], false, 'normal'),
  makeBank('2025级线性代数', 'TK20250002', 3, '王老师',
    [['线性代数讲义.pdf', 'PDF', '3.6 MB'], ['习题解答.docx', 'DOCX', '288 KB']], ['王老师', CURRENT_USER, '李老师'], false, 'normal'),
  makeBank('高数基础题库', 'TK20240003', 2, CURRENT_USER,
    [['函数与极限.pdf', 'PDF', '2.8 MB'], ['微积分基础.docx', 'DOCX', '455 KB']], [CURRENT_USER, '刘老师'], true, 'super'),
  makeBank('概率论与数理统计', 'TK20240004', 1, '陈老师',
    [['概率基础.pdf', 'PDF', '1.9 MB']], ['陈老师', CURRENT_USER], false, 'normal'),
  makeBank('大学物理（力学）', 'TK20240005', 4, '刘老师',
    [['力学讲义.pdf', 'PDF', '5.1 MB'], ['习题册.docx', 'DOCX', '640 KB'], ['实验报告模板.md', 'MD', '12 KB']], ['刘老师', CURRENT_USER, '王老师', '赵老师'], false, 'normal'),
  makeBank('高等数学综合练习', 'TK20240006', 2, '赵老师',
    [['综合练习册.pdf', 'PDF', '3.3 MB']], ['赵老师', CURRENT_USER], false, 'normal'),
]

const clone = (b: ManagedBank): ManagedBank => JSON.parse(JSON.stringify(b))
const all = () => [...ownedBanks, ...joinedBanks]
const findBank = (id: string) => all().find((b) => b.id === id)

export async function listOwned(): Promise<ManagedBank[]> {
  await delay()
  return ownedBanks.map(clone)
}

export async function listJoined(): Promise<ManagedBank[]> {
  await delay()
  return joinedBanks.map(clone)
}

export async function updateBank(id: string, patch: { name?: string; adminLevel?: AdminLevel }): Promise<ManagedBank> {
  await delay()
  const bank = findBank(id)
  if (!bank) throw new Error('题库不存在或已被删除')
  if (patch.name !== undefined) bank.name = patch.name
  if (patch.adminLevel) bank.adminLevel = patch.adminLevel
  return clone(bank)
}

export async function deleteBank(id: string): Promise<void> {
  await delay()
  const i = ownedBanks.findIndex((b) => b.id === id)
  if (i >= 0) ownedBanks.splice(i, 1)
}

export async function addDoc(bankId: string, name: string, format: string, size: string): Promise<BankDoc> {
  await delay(120)
  const bank = findBank(bankId)
  if (!bank) throw new Error('题库不存在')
  const doc: BankDoc = { id: uid('d'), name, format, size }
  bank.docs.push(doc)
  return { ...doc }
}

export async function removeDoc(bankId: string, docId: string): Promise<void> {
  await delay(120)
  const bank = findBank(bankId)
  if (!bank) throw new Error('题库不存在')
  bank.docs = bank.docs.filter((d) => d.id !== docId)
}

/** 设为管理员（级别跟随题库 adminLevel；创建者恒为超级管理员） */
export async function setAdmin(bankId: string, memberId: string): Promise<void> {
  await delay()
  const bank = findBank(bankId)
  const m = bank?.members.find((x) => x.id === memberId)
  if (!bank || !m) throw new Error('成员不存在')
  m.isAdmin = true
}

/** 取消管理员 */
export async function unsetAdmin(bankId: string, memberId: string): Promise<void> {
  await delay()
  const bank = findBank(bankId)
  const m = bank?.members.find((x) => x.id === memberId)
  if (!bank || !m) throw new Error('成员不存在')
  if (m.name === bank.creator) throw new Error('创建者不能被取消管理员')
  m.isAdmin = false
}

/** 将成员移出题库（不能移出创建者与当前用户） */
export async function removeMember(bankId: string, memberId: string): Promise<void> {
  await delay()
  const bank = findBank(bankId)
  const m = bank?.members.find((x) => x.id === memberId)
  if (!bank || !m) throw new Error('成员不存在')
  if (m.name === bank.creator) throw new Error('不能移出创建者')
  if (m.name === CURRENT_USER) throw new Error('不能移出自己，可使用退出题库')
  bank.members = bank.members.filter((x) => x.id !== memberId)
  bank.memberCount = Math.max(0, bank.memberCount - 1)
}

export async function transferBank(bankId: string, memberId: string): Promise<void> {
  await delay(260)
  const bank = findBank(bankId)
  const m = bank?.members.find((x) => x.id === memberId)
  if (!bank || !m) throw new Error('成员不存在')
  bank.creator = m.name
  // 新创建者升级为超级管理员，原创建者降为普通管理员
  bank.members.forEach((x) => {
    x.isAdmin = x.id === memberId
  })
  const oi = ownedBanks.findIndex((b) => b.id === bankId)
  if (oi >= 0) ownedBanks.splice(oi, 1)
  const target = joinedBanks.find((b) => b.id === bankId)
  if (target) {
    target.adminLevel = 'super'
  } else {
    const moved = clone(bank)
    moved.adminLevel = 'super'
    joinedBanks.push(moved)
  }
}

export async function joinByCode(code: string): Promise<ManagedBank> {
  await delay(320)
  const clean = code.trim().toUpperCase()
  const target = all().find((b) => b.code.toUpperCase() === clean)
  if (!target) throw new Error('未找到该编号的题库，请确认后重试')
  if (joinedBanks.some((b) => b.id === target.id)) throw new Error('你已在该题库中')
  const joined = clone(target)
  joined.quitted = false
  if (!joined.members.some((m) => m.name === CURRENT_USER)) {
    joined.members.push(member(CURRENT_USER))
    joined.memberCount = Math.min(joined.capacity, joined.memberCount + 1)
  }
  joinedBanks.push(joined)
  return clone(joined)
}

export async function quitBank(id: string): Promise<void> {
  await delay()
  const bank = joinedBanks.find((b) => b.id === id)
  if (!bank) throw new Error('题库不存在')
  bank.quitted = true
}

/** 当前用户在该题库是否拥有管理员权限 */
export function isMyAdmin(bank: ManagedBank): boolean {
  return bank.members.some((m) => m.name === CURRENT_USER && m.isAdmin)
}

/** 当前用户在该题库是否为超级管理员（创建者，或普通题库的管理员） */
export function isMySuperAdmin(bank: ManagedBank): boolean {
  if (!isMyAdmin(bank)) return false
  return bank.creator === CURRENT_USER || bank.adminLevel === 'super'
}
