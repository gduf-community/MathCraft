import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, X } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { TYPE_LABELS, TYPE_ORDER } from '../../../constants'
import { exportQuestionsDocx } from '../../../api/exportDocx'
import type { QuestionType } from '../../../types'

interface Props {
  onClose: () => void
}

/**
 * 导出弹窗：与组卷交互一致。
 * - 未选中题目时入口按钮禁用，进入弹窗的即是被勾选题目
 * - 文档名称、导出答案、导出解析、答案与解析位置（每题下方或文末）
 * - 按题型模块整体排序，文档内仅保留题型名称与全卷连续题号
 */
export default function ExportModal({ onClose }: Props) {
  const { questions, selectedIds, showToast } = useApp()

  const pool = useMemo(() => questions.filter((q) => selectedIds.includes(q.id)), [questions, selectedIds])

  const [modules, setModules] = useState<QuestionType[]>(() => {
    const present = new Set(pool.map((q) => q.type))
    return TYPE_ORDER.filter((t) => present.has(t))
  })
  const [docName, setDocName] = useState(
    () => `试卷_${new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })}`,
  )
  const [includeAnswer, setIncludeAnswer] = useState(true)
  const [includeAnalysis, setIncludeAnalysis] = useState(true)
  const [placement, setPlacement] = useState<'inline' | 'end'>('inline')
  const [busy, setBusy] = useState(false)

  const move = (idx: number, dir: -1 | 1) => {
    setModules((prev) => {
      const next = [...prev]
      const target = idx + dir
      if (target < 0 || target >= next.length) return prev
      ;[next[idx], next[target]] = [next[target], next[idx]]
      return next
    })
  }

  const counts = useMemo(() => {
    const map = new Map<QuestionType, number>()
    for (const q of pool) map.set(q.type, (map.get(q.type) ?? 0) + 1)
    return map
  }, [pool])

  const runExport = async () => {
    if (busy) return
    if (!docName.trim()) {
      showToast('请填写导出文档名称')
      return
    }
    setBusy(true)
    try {
      await exportQuestionsDocx(docName.trim(), includeAnswer, includeAnalysis, placement, modules, pool)
      showToast('导出成功，已开始下载')
      onClose()
    } catch (error: unknown) {
      showToast(error instanceof Error ? error.message : '导出失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-40 flex animate-fade-in items-center justify-center bg-[#0f1b33]/45 p-6"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-[560px] animate-pop flex-col rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <h3 className="text-base font-bold text-ink">导出 Word 文档</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
          <section>
            <h4 className="mb-2 text-sm font-bold text-ink">文档名称</h4>
            <input
              type="text"
              value={docName}
              maxLength={80}
              onChange={(e) => setDocName(e.target.value)}
              placeholder="请输入导出文档名称"
              className="block w-full rounded-lg border border-line px-3 py-2.5 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
            />
          </section>

          <section>
            <h4 className="mb-2 text-sm font-bold text-ink">导出内容</h4>
            <div className="space-y-2">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={includeAnswer}
                  onChange={(e) => setIncludeAnswer(e.target.checked)}
                  className="h-4 w-4 accent-primary"
                />
                导出答案
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={includeAnalysis}
                  onChange={(e) => setIncludeAnalysis(e.target.checked)}
                  className="h-4 w-4 accent-primary"
                />
                导出解析
              </label>
            </div>
          </section>

          <section>
            <h4 className="mb-2 text-sm font-bold text-ink">
              答案与解析位置 <span className="ml-1 text-xs font-normal text-ink-3">（勾选答案或解析后生效）</span>
            </h4>
            <div className="flex gap-2.5">
              <button
                type="button"
                onClick={() => setPlacement('inline')}
                className={`rounded-lg border px-4 py-2 text-sm transition-colors ${
                  placement === 'inline'
                    ? 'border-primary bg-primary-light font-medium text-primary'
                    : 'border-line bg-white text-ink-2 hover:border-primary/50'
                }`}
              >
                每题下方
              </button>
              <button
                type="button"
                onClick={() => setPlacement('end')}
                className={`rounded-lg border px-4 py-2 text-sm transition-colors ${
                  placement === 'end'
                    ? 'border-primary bg-primary-light font-medium text-primary'
                    : 'border-line bg-white text-ink-2 hover:border-primary/50'
                }`}
              >
                文末集中
              </button>
            </div>
          </section>

          <section>
            <h4 className="mb-2 text-sm font-bold text-ink">
              题型模块排序 <span className="ml-1 text-xs font-normal text-ink-3">（按模块整体调整顺序）</span>
            </h4>
            <ul className="divide-y divide-line/70 rounded-lg border border-line">
              {modules.map((t, i) => (
                <li key={t} className="flex items-center gap-3 px-4 py-3">
                  <span className="rounded bg-primary-light px-2 py-0.5 text-xs font-medium text-primary">
                    {TYPE_LABELS[t]}
                  </span>
                  <span className="flex-1 text-sm text-ink-2">{counts.get(t) ?? 0} 题</span>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      title="上移"
                      disabled={i === 0}
                      onClick={() => move(i, -1)}
                      className="rounded-md border border-line p-1 text-ink-2 transition-colors hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      <ArrowUp size={14} />
                    </button>
                    <button
                      type="button"
                      title="下移"
                      disabled={i === modules.length - 1}
                      onClick={() => move(i, 1)}
                      className="rounded-md border border-line p-1 text-ink-2 transition-colors hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      <ArrowDown size={14} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-ink-3">
              文档按题型分组，只保留题型名称与全卷连续题号，不含难度和分值。
            </p>
          </section>
        </div>

        <div className="flex items-center justify-between border-t border-line px-6 py-4">
          <span className="text-sm text-ink-3">共 {pool.length} 题 · 仅支持 Word 文档</span>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-line px-5 py-2 text-sm text-ink-2 transition-colors hover:border-ink-3 hover:text-ink"
            >
              取消
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void runExport()}
              className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-white shadow-[0_4px_12px_rgba(30,111,255,0.30)] transition-all hover:bg-[#1a5fe6] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45"
            >
              {busy ? '正在导出…' : '导出'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
