import { Bot } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import RobotAvatar from './RobotAvatar'
import QuickPrompts from './QuickPrompts'
import ChatInput from './ChatInput'

/** 智能生成标签页：欢迎态（机器人 + 快捷提问）与对话态 */
export default function GenerateTab() {
  const { messages, botThinking } = useApp()
  const showWelcome = messages.length === 0 && !botThinking

  return (
    <div className="flex h-full min-h-0 flex-col">
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
                    {m.role === 'user' ? '张' : <Bot size={16} />}
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
    </div>
  )
}
