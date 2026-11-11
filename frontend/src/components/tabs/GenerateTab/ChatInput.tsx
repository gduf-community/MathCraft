import { SendHorizontal, Square, X } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import SegmentedControl, { MODE_LABEL } from '../../ui/SegmentedControl'

/** 底部输入区：模式分段贴在输入框左上边缘，待发送图片预览、消息输入与发送 */
export default function ChatInput() {
  const {
    inputDraft, setInputDraft, sendChat, botThinking, showToast,
    selectedDocId, pauseChat, chatImages, removeChatImage,
    mode, setMode, sessionMode, modeVisible, messages,
  } = useApp()
  const canSend = (inputDraft.trim().length > 0 || chatImages.length > 0) && !botThinking

  const submit = () => {
    if (!canSend) return
    if (!selectedDocId) {
      showToast('请先在右侧选择知识库文档，才能基于知识库出题')
      return
    }
    const text = inputDraft
    const images = chatImages
    setInputDraft('')
    void sendChat(text, images)
  }

  const onModeChange = (next: typeof mode) => {
    setMode(next)
    if (!botThinking && messages.length > 0 && next !== sessionMode) {
      // 切换完成后立即告知 AI；模式作为显式参数传递，后端确认后控制器隐藏
      void sendChat(`已切换到${MODE_LABEL[next]}模式`, [], { switchOnly: true, mode: next })
    }
  }

  return (
    <div className="shrink-0 px-6 pb-5">
      <div className="relative">
        {/* 分段控制器嵌在输入框左上边缘，底边压住卡片顶边框 */}
        {modeVisible && (
          <div className="absolute bottom-full left-1 z-10">
            <SegmentedControl value={mode} onChange={onModeChange} />
          </div>
        )}
        <div className="rounded-xl border border-line bg-white p-3 shadow-[0_-2px_16px_rgba(30,90,180,0.05)]">
        {chatImages.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {chatImages.map((src, i) => (
              <div key={`${i}-${src.slice(24, 40)}`} className="group relative h-16 w-16 overflow-hidden rounded-lg border border-line">
                <img src={src} alt={`待发送图片 ${i + 1}`} className="h-full w-full object-cover" />
                <button
                  type="button"
                  title="移除图片"
                  onClick={() => removeChatImage(i)}
                  className="absolute right-0.5 top-0.5 rounded-full bg-ink/70 p-0.5 text-white opacity-0 transition-opacity group-hover:opacity-100"
                >
                  <X size={10} />
                </button>
              </div>
            ))}
          </div>
        )}
        <textarea
          rows={chatImages.length > 0 ? 2 : 1}
          maxLength={2000}
          value={inputDraft}
          onChange={(e) => setInputDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder={chatImages.length > 0 ? '补充对图片的说明，或直接发送…' : '请输入你的问题，或粘贴相关文档内容...'}
          className="block w-full resize-none bg-transparent px-1 text-sm leading-6 text-ink outline-none placeholder:text-ink-3"
        />
        <div className="mt-1 flex items-center justify-end gap-4">
          <span className="text-xs text-ink-3">{inputDraft.length}/2000</span>
          {botThinking ? (
            <button
              type="button"
              onClick={pauseChat}
              className="flex items-center gap-1.5 rounded-lg bg-ink px-5 py-2 text-sm font-medium text-white transition-all hover:bg-ink/90 active:scale-[0.97]"
            >
              <Square size={12} fill="currentColor" />
              暂停
            </button>
          ) : (
            <button
              type="button"
              disabled={!canSend}
              onClick={submit}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-white transition-all hover:bg-[#1a5fe6] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45"
            >
              <SendHorizontal size={14} />
              发送
            </button>
          )}
        </div>
        </div>
      </div>
    </div>
  )
}
