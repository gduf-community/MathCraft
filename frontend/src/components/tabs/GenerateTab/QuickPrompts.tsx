import { CircleCheck, FileText, LayoutGrid, ListChecks } from 'lucide-react'
import { useApp } from '../../../store/AppContext'

const PROMPTS = [
  { icon: FileText, text: '生成一套关于「函数」的测试题' },
  { icon: ListChecks, text: '根据文档内容出一套试卷' },
  { icon: CircleCheck, text: '我需要一些判断题，难度中等' },
  { icon: LayoutGrid, text: '请生成多种题型的综合练习题' },
]

/** 快捷提问仅填入草稿，供用户编辑后发送。 */
export default function QuickPrompts() {
  const { setInputDraft, botThinking, confirmBusy, pendingConfirm } = useApp()
  const interactionBusy = botThinking || confirmBusy || pendingConfirm !== null

  return (
    <div className="mt-9 grid w-full max-w-[520px] grid-cols-1 gap-3 sm:grid-cols-2">
      {PROMPTS.map(({ icon: Icon, text }) => (
        <button
          key={text}
          type="button"
          disabled={interactionBusy}
          onClick={() => {
            if (!interactionBusy) setInputDraft(text)
          }}
          className="flex min-w-0 items-center gap-2 rounded-lg border border-line bg-white px-4 py-3 text-left text-[14px] text-ink-2 transition-all hover:-translate-y-px hover:border-primary/50 hover:text-primary hover:shadow-[0_4px_12px_rgba(30,111,255,0.10)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-45 motion-reduce:transform-none motion-reduce:transition-none"
        >
          <Icon size={15} aria-hidden="true" className="shrink-0 text-primary" />
          <span className="truncate">{text}</span>
        </button>
      ))}
    </div>
  )
}
