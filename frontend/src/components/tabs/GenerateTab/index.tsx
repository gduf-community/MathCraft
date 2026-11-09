import { useEffect, useState } from 'react'
import type { DragEvent } from 'react'
import { Bot, Copy, FileUp, Pencil, RotateCcw } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import RobotAvatar from './RobotAvatar'
import QuickPrompts from './QuickPrompts'
import ChatInput from './ChatInput'

/** Agent出题标签页：欢迎态（机器人 + 快捷提问）与对话态；支持拖拽文档到对话区上传 */
export default function GenerateTab() {
  const { messages, botThinking, uploadDocument, profile, retryChat, editChat, showToast, chatProgress, chatStartedAt } = useApp()
  const showWelcome = messages.length === 0 && !botThinking
  const [dragOver, setDragOver] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!botThinking) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [botThinking])

  const elapsed = chatStartedAt ? Math.max(0, Math.floor((now - chatStartedAt) / 1000)) : 0
  const elapsedText = elapsed >= 60 ? `${Math.floor(elapsed / 60)} 分 ${elapsed % 60} 秒` : `${elapsed} 秒`

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) void uploadDocument(file)
  }

  return (
    <div
      className="relative flex h-full min-h-0 flex-col"
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={(e) => {
        e.preventDefault()
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false)
      }}
      onDrop={onDrop}
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        {showWelcome ? (
          <div className="flex h-full flex-col items-center justify-center px-8 pb-4">
            <RobotAvatar />
            <h2 className="mt-4 text-[24px] font-bold text-ink">你好，我是AI出题助手</h2>
            <p className="mt-3 max-w-[460px] text-center text-sm leading-6 text-ink-2">
              我可以根据你的需求，结合知识库内容，为你生成高质量的试题。
              <br />
              你可以直接提出出题要求，或告诉我相关的知识点、难度、题型等信息。
            </p>
            <QuickPrompts />
          </div>
        ) : (
          <div className="mx-auto flex w-full max-w-[880px] flex-col gap-4 px-8 py-6">
            {messages.map((m) => (
              <div key={m.id} className={`group flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`flex max-w-[80%] items-start gap-2 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
                  <span
                    className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm ${
                      m.role === 'user' ? 'bg-primary font-semibold text-white' : 'bg-primary-light text-primary'
                    }`}
                  >
                    {m.role === "user" ? profile.name.charAt(0) : <Bot size={16} />}
                  </span>
                  <div className="flex min-w-0 flex-col">
                    <div
                      className={`rounded-2xl px-4 py-2.5 text-[15px] leading-7 ${
                        m.role === 'user'
                          ? 'rounded-tr-sm bg-primary text-white'
                          : 'rounded-tl-sm border border-line bg-white text-ink'
                      }`}
                    >
                      {m.text}
                    </div>
                    {m.role === 'user' && (
                      <div className="mt-1 flex justify-end gap-0.5 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100">
                        <button
                          type="button"
                          title="复制"
                          onClick={() => {
                            void navigator.clipboard?.writeText(m.text).then(
                              () => showToast('已复制'),
                              () => showToast('复制失败'),
                            )
                          }}
                          className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-primary"
                        >
                          <Copy size={13} />
                        </button>
                        <button
                          type="button"
                          title="回退并重新发送"
                          disabled={botThinking}
                          onClick={() => retryChat(m.id)}
                          className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-primary"
                        >
                          <RotateCcw size={13} />
                        </button>
                        <button
                          type="button"
                          title="编辑后重发"
                          disabled={botThinking}
                          onClick={() => editChat(m.id)}
                          className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-primary"
                        >
                          <Pencil size={13} />
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
            {botThinking && (
              <div className="flex justify-start">
                <div className="flex flex-col gap-2 rounded-2xl rounded-tl-sm border border-line bg-white px-4 py-3">
                  <div className="flex items-center gap-1.5">
                    <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/60" />
                    <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/60 [animation-delay:0.15s]" />
                    <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/60 [animation-delay:0.3s]" />
                  </div>
                  {chatProgress?.stage && (
                    <div className="flex items-center gap-2">
                      <span className="h-1 w-24 overflow-hidden rounded-full bg-page">
                        <span
                          className="block h-full rounded-full bg-primary transition-all duration-500"
                          style={{ width: `${Math.max(4, Math.min(100, chatProgress.percent))}%` }}
                        />
                      </span>
                      <span className="text-xs text-ink-3">
                        {chatProgress.stage}
                        <span className="ml-1 text-ink-3/70">· 已等待 {elapsedText}</span>
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
      <ChatInput />

      {/* 拖拽上传遮罩 */}
      {dragOver && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-primary-light/70 backdrop-blur-[1px]">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-white text-primary shadow-lg">
            <FileUp size={26} />
          </span>
          <p className="text-sm font-semibold text-primary">松开以上传文档到当前知识库</p>
          <p className="text-xs text-ink-2">支持 PDF / DOCX / XLSX / MD，上传后自动入库</p>
        </div>
      )}
    </div>
  )
}
