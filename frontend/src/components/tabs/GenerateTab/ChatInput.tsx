import { FileUp, Loader2, Paperclip, SendHorizontal } from 'lucide-react'
import { useApp } from '../../../store/AppContext'

/** 底部输入区：消息输入、字数统计、上传与发送 */
export default function ChatInput() {
  const { inputDraft, setInputDraft, sendChat, botThinking, showToast, selectedDocId } = useApp()
  const canSend = inputDraft.trim().length > 0 && !botThinking

  const submit = () => {
    if (!canSend) return
    if (!selectedDocId) {
      showToast('请先在右侧选择知识库文档，才能基于知识库出题')
      return
    }
    const text = inputDraft
    setInputDraft('')
    void sendChat(text)
  }

  return (
    <div className="shrink-0 px-6 pb-5">
      <div className="rounded-xl border border-line bg-white p-3 shadow-[0_-2px_16px_rgba(30,90,180,0.05)]">
        <textarea
          rows={2}
          maxLength={2000}
          value={inputDraft}
          onChange={(e) => setInputDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder="请输入你的问题，或粘贴相关文档内容..."
          className="block w-full resize-none bg-transparent px-1 text-sm leading-6 text-ink outline-none placeholder:text-ink-3"
        />
        <div className="mt-1 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              type="button"
              title="附件"
              onClick={() => showToast('演示环境暂不支持上传附件')}
              className="rounded-md p-1.5 text-ink-3 transition-colors hover:bg-primary-weak hover:text-primary"
            >
              <Paperclip size={16} />
            </button>
            <button
              type="button"
              onClick={() => showToast('演示环境暂不支持上传文件')}
              className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-ink-2 transition-colors hover:bg-primary-weak hover:text-primary"
            >
              <FileUp size={15} />
              上传文件
            </button>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-xs text-ink-3">{inputDraft.length}/2000</span>
            <button
              type="button"
              disabled={!canSend}
              onClick={submit}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-white transition-all hover:bg-[#1a5fe6] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45"
            >
              {botThinking ? <Loader2 size={14} className="animate-spin" /> : <SendHorizontal size={14} />}
              发送
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
