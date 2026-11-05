/** 题库真实 API 适配层：保留题库页原有数据结构，数据全部来自后端。 */
import {
  type ApiBank,
  type ApiBankMember,
  type ApiDocument,
  createBank as createBankApi,
  deleteBank as deleteBankApi,
  deleteDocument,
  downloadDocument,
  getBank,
  getDocument,
  joinBank,
  listBankMembers,
  addBankMember,
  listBanks,
  listDocuments,
  quitBank,
  removeBankMember,
  reprocessDocument,
  setBankMemberRole,
  transferBank as transferBankApi,
  updateBank as updateBankApi,
  uploadDocument,
  formatFileSize,
} from './backend'

export interface BankDoc {
  id: string
  name: string
  format: string
  size: string
  status?: string
  progress?: number
}

export interface BankMember {
  id: string
  name: string
  /** 成员权限：创建者、可编辑或只读。 */
  role: 'creator' | 'editor' | 'readonly'
  userId: string
  isMe: boolean
  isCreator: boolean
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
  quitted?: boolean
  source: 'owned' | 'joined'
  myRole: 'creator' | 'editor' | 'readonly'
  canUpload: boolean
  canDownload: boolean
  canDeleteDoc: boolean
  canManageMembers: boolean
  canEdit: boolean
  canTransfer: boolean
  canDelete: boolean
}

export let CURRENT_USER = ''

export function setCurrentUser(name: string) {
  CURRENT_USER = name
}

function mapDoc(d: ApiDocument): BankDoc {
  return {
    id: d.id,
    name: d.name,
    format: d.format,
    size: formatFileSize(d.size_bytes),
    status: d.status,
    progress: d.progress,
  }
}

function mapMember(m: ApiBankMember): BankMember {
  return {
    id: m.id,
    name: m.user.display_name,
    role: m.role,
    userId: m.user.id,
    isMe: m.is_me,
    isCreator: m.is_creator,
  }
}

async function enrich(bank: ApiBank): Promise<ManagedBank> {
  const [members, docs] = await Promise.all([listBankMembers(bank.id), listDocuments(bank.id)])
  return {
    id: bank.id,
    name: bank.name,
    code: bank.code,
    memberCount: bank.member_count,
    capacity: bank.capacity,
    creator: bank.creator?.display_name ?? '',
    docs: docs.map(mapDoc),
    members: members.map(mapMember),
    quitted: bank.quitted,
    source: bank.source,
    myRole: bank.my_role,
    canUpload: bank.can_upload_document,
    canDownload: bank.can_download_document,
    canDeleteDoc: bank.can_delete_document,
    canManageMembers: bank.can_manage_members,
    canEdit: bank.can_edit_bank,
    canTransfer: bank.can_transfer_bank,
    canDelete: bank.can_delete_bank,
  }
}

export async function listOwned(): Promise<ManagedBank[]> {
  const banks = await listBanks('owned')
  return Promise.all(banks.map(enrich))
}

export async function listJoined(): Promise<ManagedBank[]> {
  const banks = await listBanks('joined')
  return Promise.all(banks.map(enrich))
}

export async function getBankDetail(id: string): Promise<ManagedBank> {
  return enrich(await getBank(id))
}

export async function updateBank(
  id: string,
  patch: { name?: string },
): Promise<ManagedBank> {
  const updated = await updateBankApi(id, {
    name: patch.name,
  })
  return enrich(updated)
}

export async function deleteBank(id: string): Promise<void> {
  await deleteBankApi(id)
}

export async function createBank(name: string): Promise<ManagedBank> {
  return enrich(await createBankApi(name))
}

export async function joinByCode(code: string): Promise<ManagedBank> {
  return enrich(await joinBank(code))
}

export async function quitBankById(id: string): Promise<void> {
  await quitBank(id)
}

export async function addMember(bankId: string, account: string, role: 'editor' | 'readonly'): Promise<BankMember> {
  const member = await addBankMember(bankId, account, role)
  return mapMember(member)
}

export async function setMemberRole(bankId: string, memberId: string, role: 'editor' | 'readonly'): Promise<void> {
  await setBankMemberRole(bankId, memberId, role)
}

export async function removeMember(bankId: string, memberId: string): Promise<void> {
  await removeBankMember(bankId, memberId)
}

export async function transferBank(bankId: string, memberId: string): Promise<void> {
  await transferBankApi(bankId, memberId)
}

export async function removeDoc(bankId: string, docId: string): Promise<void> {
  await deleteDocument(bankId, docId)
}

export async function downloadDoc(bankId: string, docId: string, name: string): Promise<void> {
  await downloadDocument(bankId, docId, name)
}

export async function reprocessDoc(bankId: string, docId: string): Promise<void> {
  await reprocessDocument(bankId, docId)
}

export async function uploadDoc(
  bankId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<string> {
  const result = await uploadDocument(bankId, file, onProgress)
  return result.document_id
}

/** 上传并等待后端完成解析、OCR、切片、向量化。 */
export async function uploadAndWait(
  bankId: string,
  file: File,
  onStage?: (phase: 'upload' | 'vector' | 'done', percent: number, stage: string) => void,
): Promise<BankDoc> {
  const docId = await uploadDoc(bankId, file, (pct) => onStage?.('upload', pct, '正在上传'))
  for (let i = 0; i < 120; i += 1) {
    const doc = await getDocument(bankId, docId)
    if (doc.status === 'ready') {
      onStage?.('done', 100, '入库完成')
      return mapDoc(doc)
    }
    if (doc.status === 'failed') {
      throw new Error(doc.error_message || '文档入库失败')
    }
    onStage?.('vector', doc.progress, doc.stage || '正在解析入库')
    await new Promise((r) => setTimeout(r, 1000))
  }
  throw new Error('文档入库超时，请稍后在题库中查看状态')
}

export function isMyAdmin(bank: ManagedBank): boolean {
  return bank.myRole === 'creator' || bank.myRole === 'editor'
}

export function isMySuperAdmin(bank: ManagedBank): boolean {
  return bank.myRole === 'creator'
}
