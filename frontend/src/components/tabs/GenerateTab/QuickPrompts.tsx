import { CircleCheck, FileText, LayoutGrid, ListChecks } from 'lucide-react'
import { useApp } from '../../../store/AppContext'

const PROMPTS = [
  { icon: FileText, text: '生成一套关于「函数」的测试题' },
  { icon: ListChecks, text: '根据文档内容出一套试卷' },
  { icon: CircleCheck, text: '我需要一些判断题，难度中等' },
  { icon: LayoutGrid, text: '请生成多种题型的综合练习题' },
]

/** 快捷提问按钮：点击填入输入框，可再编辑后发送 */
export default function QuickPrompts() {
  const { setInputDraft } = useApp()
  return (
    <div className="mt-9 grid max-w-[520px] grid-cols-2 gap-3">
      {PROMPTS.map(({ icon: Icon, text }) => (
        <button
          key={text}
          type="button"
          onClick={() => setInputDraft(text)}
          className="flex items-center gap-2 rounded-lg border border-line bg-white px-4 py-3 text-left text-[14px] text-ink-2 transition-all hover:-translate-y-px hover:border-primary/50 hover:text-primary hover:shadow-[0_4px_12px_rgba(30,111,255,0.10)]"
        >
          <Icon size={15} className="shrink-0 text-primary" />
          <span className="truncate">{text}</span>
        </button>
      ))}
    </div>
  )
}
