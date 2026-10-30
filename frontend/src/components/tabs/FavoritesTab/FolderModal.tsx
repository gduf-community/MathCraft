import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Folder, Inbox, X } from 'lucide-react'
import type { FavoriteFolder } from '../../../types/favorites'

interface FormProps {
  /** 传入表示重命名，不传表示新建 */
  folder?: FavoriteFolder
  onClose: () => void
  onSubmit: (name: string, description: string) => Promise<boolean>
}

/** A-11 新建 / 重命名收藏夹弹窗 */
export function FolderFormModal({ folder, onClose, onSubmit }: FormProps) {
  const [name, setName] = useState(folder?.name ?? '')
  const [description, setDescription] = useState(folder?.description ?? '')
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || !name.trim()) {
      inputRef.current?.focus()
      return
    }
    setBusy(true)
    const ok = await onSubmit(name.trim(), description.trim())
    if (!ok) setBusy(false)
  }

  return (
    <div
      className="fixed inset-0 z-40 flex animate-fade-in items-center justify-center bg-[#0f1b33]/30 p-6"
      onClick={onClose}
    >
      <form
        className="w-full max-w-[420px] animate-pop rounded-2xl bg-white p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        onSubmit={(event) => void submit(event)}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-[17px] font-bold text-ink">{folder ? '重命名收藏夹' : '新建收藏夹'}</h3>
            <p className="mt-1 text-xs leading-6 text-ink-3">
              收藏夹仅自己可见，用于把收藏的题目按专题或教学进度归类。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="rounded-lg p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        <label className="mt-4 flex flex-col gap-1.5 text-sm font-medium text-ink">
          名称
          <input
            ref={inputRef}
            value={name}
            maxLength={20}
            onChange={(event) => setName(event.target.value)}
            placeholder="如：导数专题（20 字以内）"
            className="h-10 rounded-lg border border-line px-3 text-sm font-normal text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
          />
        </label>

        <label className="mt-3 flex flex-col gap-1.5 text-sm font-medium text-ink">
          说明（可选）
          <input
            value={description}
            maxLength={40}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="如：期中复习用，重点看单调性"
            className="h-10 rounded-lg border border-line px-3 text-sm font-normal text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
          />
        </label>

        <div className="mt-5 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:border-ink-3 hover:text-ink"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={!name.trim() || busy}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-[0_4px_14px_rgba(30,111,255,0.32)] transition-colors hover:bg-[#1a5fe6] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? '保存中…' : folder ? '保存' : '创建'}
          </button>
        </div>
      </form>
    </div>
  )
}

interface ConfirmProps {
  title: string
  message: string
  confirmText: string
  onClose: () => void
  onConfirm: () => void
}

/** 删除收藏夹等破坏性操作的二次确认 */
export function ConfirmModal({ title, message, confirmText, onClose, onConfirm }: ConfirmProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-40 flex animate-fade-in items-center justify-center bg-[#0f1b33]/30 p-6"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[420px] animate-pop rounded-2xl bg-white p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className="text-[17px] font-bold text-ink">{title}</h3>
        <p className="mt-2 text-sm leading-7 text-ink-2">{message}</p>
        <div className="mt-5 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:border-ink-3 hover:text-ink"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-lg bg-danger px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600"
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}

interface MoveProps {
  folders: FavoriteFolder[]
  currentFolderId?: string
  count: number
  onClose: () => void
  onMove: (folderId: string) => Promise<void>
}

/** 批量移动收藏夹 */
export function MoveFolderModal({ folders, currentFolderId, count, onClose, onMove }: MoveProps) {
  const [busyId, setBusyId] = useState<string | null>(null)

  const move = async (folderId: string) => {
    if (busyId) return
    setBusyId(folderId)
    await onMove(folderId)
    setBusyId(null)
  }

  return (
    <div
      className="fixed inset-0 z-40 flex animate-fade-in items-center justify-center bg-[#0f1b33]/30 p-6"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[380px] animate-pop rounded-2xl bg-white p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className="text-[17px] font-bold text-ink">移动到收藏夹</h3>
        <p className="mt-1 text-xs text-ink-3">已选 {count} 道题，选择目标收藏夹。</p>
        <ul className="mt-4 space-y-1.5">
          {folders.map((folder) => {
            const current = folder.id === currentFolderId
            return (
              <li key={folder.id}>
                <button
                  type="button"
                  disabled={current || busyId !== null}
                  onClick={() => void move(folder.id)}
                  className={`flex w-full items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
                    current
                      ? 'cursor-not-allowed border-line bg-page text-ink-3'
                      : 'border-line bg-white text-ink hover:border-primary/50 hover:bg-primary-weak hover:text-primary'
                  }`}
                >
                  {folder.id === 'inbox' ? <Inbox size={16} /> : <Folder size={16} />}
                  <span className="flex-1 truncate">{folder.name}</span>
                  {current && <span className="text-xs text-ink-3">当前</span>}
                  {busyId === folder.id && <span className="text-xs text-primary">移动中…</span>}
                </button>
              </li>
            )
          })}
        </ul>
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:border-ink-3 hover:text-ink"
          >
            取消
          </button>
        </div>
      </div>
    </div>
  )
}
