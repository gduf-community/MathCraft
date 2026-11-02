import { useState } from 'react'
import type { DragEvent } from 'react'
import { Bot, FileUp } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import RobotAvatar from './RobotAvatar'
import QuickPrompts from './QuickPrompts'
import ChatInput from './ChatInput'

/** Agent出题标签页：欢迎态（机器人 + 快捷提问）与对话态；支持拖拽文档到对话区上传 */
export default function GenerateTab() {
  const { messages, botThinking, uploadDocument, profile } = useApp()
  const showWelcome = messages.length === 0 && !botThinking
  const [dragOver, setDragOver] = useState(false)

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
              <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`flex max-w-[80%] items-start gap-2 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
                  <span
                    className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm ${
                      m.role === 'user' ? 'bg-primary font-semibold text-white' : 'bg-primary-light text-primary'
                    }`}
                  >
                    {m.role === "user" ? <img src={profile.avatar} alt="" className="h-8 w-8 rounded-full object-cover" /> : <Bot size={16} />}
                  </span>
                  <div
                    className={`rounded-2xl px-4 py-2.5 text-[15px] leading-7 ${
                      m.role === 'user'
                        ? 'rounded-tr-sm bg-primary text-white'
                        : 'rounded-tl-sm border border-line bg-white text-ink'
                    }`}
                  >
                    {m.text}
                  </div>
                </div>
              </div>
            ))}
            {botThinking && (
              <div className="flex justify-start">
                <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm border border-line bg-white px-4 py-3">
                  <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/60" />
                  <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/60 [animation-delay:0.15s]" />
                  <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/60 [animation-delay:0.3s]" />
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
