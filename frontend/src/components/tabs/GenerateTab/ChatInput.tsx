import { CheckCircle2, LoaderCircle, ShieldAlert, SendHorizontal, Square, X, XCircle } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { CHAT_MODE_LABELS } from '../../../types'
import SegmentedControl from '../../ui/SegmentedControl'

/** 数据管理高危操作的输入框附着审批弹窗：简洁说明操作内容，同意执行 / 拒绝取消 */
function ConfirmOverlay() {
  const { pendingConfirm, confirmBusy, confirmOperation } = useApp()
  if (!pendingConfirm) return null
  const isDelete = pendingConfirm.action === 'delete'
  const verb = isDelete ? '删除' : '重命名'
  const headline = `是否确定要${verb} ${pendingConfirm.affected} 条${pendingConfirm.entity_label}？`
  const firstSample = pendingConfirm.samples[0]
  const restCount = pendingConfirm.samples.length - 1
  return (
    <div
      className="absolute bottom-full right-0 z-30 mb-2 w-[min(520px,94%)] animate-pop rounded-xl border border-amber-300 bg-white shadow-[0_12px_36px_rgba(30,90,180,0.14)]"
      role="alertdialog"
      aria-label="高危操作确认"
    >
      <div className="flex items-start gap-2.5 px-4 pb-2.5 pt-3.5">
        <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${isDelete ? 'bg-red-50 text-red-500' : 'bg-primary-light text-primary'}`}>
          <ShieldAlert size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold leading-6 text-ink">{headline}</p>
          {firstSample && (
            <p className="mt-0.5 truncate text-xs text-ink-2">
              {firstSample}
              {restCount > 0 && <span className="ml-1 text-ink-3">等 {pendingConfirm.affected} 条记录</span>}
            </p>
          )}
          {pendingConfirm.explanation && (
            <p className="mt-0.5 text-xs text-ink-3">{pendingConfirm.explanation}</p>
          )}
        </div>
      </div>
      <div className="flex items-center justify-end gap-2 border-t border-line/70 px-4 py-2.5">
        <button
          type="button"
          disabled={confirmBusy}
          onClick={() => void confirmOperation(false)}
          className="flex items-center gap-1 rounded-lg border border-line bg-white px-3.5 py-1.5 text-sm text-ink-2 transition-colors hover:bg-page disabled:cursor-not-allowed disabled:opacity-45"
        >
          <XCircle size={14} />
          拒绝
        </button>
        <button
          type="button"
          disabled={confirmBusy}
          onClick={() => void confirmOperation(true)}
          className={`flex items-center gap-1 rounded-lg px-3.5 py-1.5 text-sm font-medium text-white transition-all active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45 ${
            isDelete ? 'bg-red-500 hover:bg-red-500/90' : 'bg-primary hover:bg-[#1a5fe6]'
          }`}
        >
          <CheckCircle2 size={14} />
          {confirmBusy ? '执行中…' : '同意执行'}
        </button>
      </div>
    </div>
  )
}

/** 底部输入区：模式分段贴在输入框左上边缘，待发送图片预览、消息输入与发送 */
export default function ChatInput() {
  const {
    inputDraft, setInputDraft, sendChat, botThinking, showToast,
    selectedDocId, pauseChat, chatPauseStatus, chatImages, removeChatImage,
    mode, setMode, sessionMode, modeVisible, messages, confirmBusy, pendingConfirm,
    sessionLoading, questionsClearing, generating, generationRecoveryError,
    modelSettings,
  } = useApp()
  // 未配置 DeepSeek API Key 时禁止发送；配置读取中不拦截
  const deepseekReady = modelSettings ? modelSettings.deepseek_key_configured : true
  const interactionBusy = botThinking || chatPauseStatus != null || sessionLoading || questionsClearing || generating
    || generationRecoveryError !== null || confirmBusy || pendingConfirm !== null
  const canSend = (inputDraft.trim().length > 0 || chatImages.length > 0) && !interactionBusy && deepseekReady

  const submit = () => {
    if (!deepseekReady) {
      showToast('请先在「个人中心 → API 配置」保存 DeepSeek API Key，再发送出题请求')
      return
    }
    if (!canSend) return
    if (!selectedDocId) {
      showToast('请先在右侧选择知识库文档，才能基于知识库出题')
      return
    }
    const text = inputDraft
    const images = chatImages
    void sendChat(text, images)
  }

  const onModeChange = (next: typeof mode) => {
    if (interactionBusy) return
    setMode(next)
    if (!botThinking && messages.length > 0 && next !== sessionMode) {
      // 切换完成后立即告知 AI；模式作为显式参数传递，后端确认后控制器隐藏
      void sendChat(`已切换到${CHAT_MODE_LABELS[next]}模式`, [], { switchOnly: true, mode: next })
    }
  }

  return (
    <div className="shrink-0 px-6 pb-4">
      <div className="relative">
        {/* 高危操作审批弹窗：附着在输入框上方，确认后才执行 */}
        {pendingConfirm && <ConfirmOverlay />}
        {/* 分段控制器嵌在输入框左上边缘，底边压住卡片顶边框 */}
        {modeVisible && !pendingConfirm && (
          <div className="absolute bottom-full left-1 z-10">
            <SegmentedControl value={mode} onChange={onModeChange} disabled={interactionBusy} />
          </div>
        )}
        <div className="rounded-xl border border-line bg-white p-2.5 shadow-[0_-2px_16px_rgba(30,90,180,0.05)]">
        {chatImages.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {chatImages.map((src, i) => (
              <div key={`${i}-${src.slice(24, 40)}`} className="group relative h-16 w-16 overflow-hidden rounded-lg border border-line">
                <img src={src} alt={`待发送图片 ${i + 1}`} className="h-full w-full object-cover" />
                <button
                  type="button"
                  title="移除图片"
                  aria-label={`移除待发送图片 ${i + 1}`}
                  onClick={() => removeChatImage(i)}
                  className="absolute right-0.5 top-0.5 rounded-full bg-ink/70 p-0.5 text-white transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100"
                >
                  <X size={10} />
                </button>
              </div>
            ))}
          </div>
        )}
        <textarea
          rows={Math.min(6, Math.max(1, inputDraft.split('\n').length))}
          aria-label="出题消息"
          maxLength={2000}
          value={inputDraft}
          onChange={(e) => setInputDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder={chatImages.length > 0 ? '补充对图片的说明，或直接发送…' : '请输入你的问题，或粘贴相关文档内容...'}
          className="block w-full resize-none bg-transparent px-1 text-sm leading-6 text-ink outline-none placeholder:text-ink-3"
        />
        <div className="mt-0.5 flex flex-wrap items-center justify-between gap-2">
          {chatPauseStatus === 'failed' && (
            <div className="flex items-center gap-2 text-xs text-ink-2">
              <span role="status">暂停未确认</span>
              <button type="button" onClick={pauseChat} className="font-medium text-primary underline">
                重试暂停
              </button>
            </div>
          )}
          {!deepseekReady && (
            <span className="text-xs text-red-600">未配置 DeepSeek API Key，无法发送；请前往「个人中心 → API 配置」保存</span>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-3">
            <span className="text-xs text-ink-3">{inputDraft.length}/2000</span>
            {chatPauseStatus != null ? (
              <button
                type="button"
                disabled
                aria-busy={chatPauseStatus === 'pending'}
                className="flex cursor-not-allowed items-center gap-1.5 rounded-lg bg-line px-4 py-1.5 text-sm font-medium text-ink-2"
              >
                {chatPauseStatus === 'pending' && (
                  <LoaderCircle size={14} aria-hidden="true" className="motion-safe:animate-spin" />
                )}
                {chatPauseStatus === 'pending' ? '正在暂停' : '暂停未确认'}
              </button>
            ) : botThinking ? (
              <button
                type="button"
                onClick={pauseChat}
                className="flex items-center gap-1.5 rounded-lg bg-ink px-4 py-1.5 text-sm font-medium text-white transition-all hover:bg-ink/90 active:scale-[0.97]"
              >
                <Square size={12} fill="currentColor" />
                暂停
              </button>
            ) : (
              <button
                type="button"
                disabled={!canSend}
                onClick={submit}
                className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-white transition-all hover:bg-[#1a5fe6] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45"
              >
                <SendHorizontal size={14} />
                发送
              </button>
            )}
          </div>
        </div>
        </div>
      </div>
    </div>
  )
}
