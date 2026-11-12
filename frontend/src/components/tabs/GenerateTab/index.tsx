import { useEffect, useState } from 'react'
import type { DragEvent } from 'react'
import { Bot, Copy, ImagePlus, Pencil, RotateCcw } from 'lucide-react'
import { useApp } from '../../../store/AppContext'
import { Latex } from '../../../lib/latex'
import RobotAvatar from './RobotAvatar'
import QuickPrompts from './QuickPrompts'
import ChatInput from './ChatInput'
import ConfirmCard from '../../ui/ConfirmCard'

/** Agent出题标签页：机器人与快捷提问欢迎态、对话及确认操作；支持图片与文档拖入 */
export default function GenerateTab() {
  const {
    messages, botThinking, uploadDocument, profile, retryChat, editChat,
    showToast, chatProgress, chatStartedAt, addChatImages, pendingConfirm, confirmOperation, confirmBusy,
  } = useApp()
  const showWelcome = messages.length === 0 && !botThinking && pendingConfirm === null
  const interactionBusy = botThinking || confirmBusy || pendingConfirm !== null
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
    const files = Array.from(e.dataTransfer.files ?? [])
    const images = files.filter((f) => f.type.startsWith('image/'))
    const docs = files.filter((f) => !f.type.startsWith('image/'))
    if (images.length) addChatImages(images)
    if (docs.length) void uploadDocument(docs[0])
  }

  // 用户消息沿用历史编辑、回退重发入口；最新 AI 回复保留重新生成。
  const lastAssistantIndex = messages.reduce((acc, m, i) => (m.role === 'assistant' ? i : acc), -1)
  const regenerateFrom = (assistantIndex: number) => {
    if (interactionBusy) return
    for (let j = assistantIndex - 1; j >= 0; j--) {
      if (messages[j].role === 'user') {
        retryChat(messages[j].id)
        return
      }
    }
  }

  const copyText = (text: string) => {
    if (!navigator.clipboard) {
      showToast('当前环境无法复制，请手动复制', 'error')
      return
    }
    void navigator.clipboard.writeText(text).then(
      () => showToast('已复制'),
      () => showToast('复制失败'),
    )
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
        if (!(e.relatedTarget instanceof Node) || !e.currentTarget.contains(e.relatedTarget)) setDragOver(false)
      }}
      onDrop={onDrop}
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        {showWelcome ? (
            <div className="flex min-h-full flex-col items-center justify-center px-8 pb-4">
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
              {messages.map((m, i) => (
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
                        className={`whitespace-pre-wrap break-words rounded-2xl px-4 py-2.5 text-[15px] leading-7 ${
                          m.role === 'user'
                            ? 'rounded-tr-sm bg-primary text-white'
                            : 'rounded-tl-sm border border-line bg-white text-ink'
                        }`}
                      >
                        {m.images?.length ? (
                          <div className="mb-2 flex flex-wrap gap-2">
                            {m.images.map((src, idx) => (
                              <img
                                key={`${i}-${idx}`}
                                src={src}
                                alt={`随消息发送的图片 ${idx + 1}`}
                                className="h-24 w-24 rounded-lg border border-white/40 object-cover"
                              />
                            ))}
                          </div>
                        ) : null}
                        {m.role === 'assistant' ? <Latex text={m.text} /> : m.text}
                      </div>
                      {m.role === 'user' && (
                        <div className="mt-1 flex justify-end gap-0.5 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100">
                          <button
                            type="button"
                            title="复制"
                            aria-label="复制用户消息"
                            onClick={() => copyText(m.text)}
                            className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-primary"
                          >
                            <Copy size={13} />
                          </button>
                          <button
                            type="button"
                            title="回退并重新发送"
                            aria-label="回退并重新发送"
                            disabled={interactionBusy}
                            onClick={() => {
                              if (!interactionBusy) retryChat(m.id)
                            }}
                            className="rounded p-1.5 text-ink-3 transition-colors hover:bg-page hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
                          >
                            <RotateCcw size={13} />
                          </button>
                          <button
                            type="button"
                            title="编辑后重发"
                            aria-label="编辑后重发"
                            disabled={interactionBusy}
                            onClick={() => {
                              if (!interactionBusy) editChat(m.id)
                            }}
                            className="rounded p-1.5 text-ink-3 transition-colors hover:bg-page hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
                          >
                            <Pencil size={13} />
                          </button>
                        </div>
                      )}
                      {m.role === 'assistant' && (
                        <div className="mt-1 flex items-center gap-0.5 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100">
                          <button
                            type="button"
                            title="复制"
                            aria-label="复制助手消息"
                            onClick={() => copyText(m.text)}
                            className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-primary"
                          >
                            <Copy size={13} />
                          </button>
                          {i === lastAssistantIndex && (
                            <button
                              type="button"
                              title="基于你的上一条消息重新生成"
                              disabled={interactionBusy}
                              onClick={() => regenerateFrom(i)}
                              className="ml-2 flex items-center gap-1 rounded p-1 text-xs text-ink-3 transition-colors hover:bg-page hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
                            >
                              <RotateCcw size={13} />
                              重新生成
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
              {botThinking && (
                <div className="flex justify-start" role="status" aria-label="正在处理对话请求" aria-live="polite">
                  <div className="flex flex-col gap-2 rounded-2xl rounded-tl-sm border border-line bg-white px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/60" />
                      <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/60 [animation-delay:0.15s]" />
                      <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/60 [animation-delay:0.3s]" />
                    </div>
                    {chatProgress?.stage && (
                      <div className="flex items-center gap-2">
                        <span className="h-1 w-24 overflow-hidden rounded-full bg-page" role="progressbar" aria-label="对话处理进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.max(0, Math.min(100, chatProgress.percent))}>
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
              {pendingConfirm && (
                <ConfirmCard
                  confirm={pendingConfirm}
                  busy={confirmBusy}
                  onAccept={() => void confirmOperation(true)}
                  onReject={() => void confirmOperation(false)}
                />
              )}
            </div>
          )}
      </div>
      <ChatInput />

      {/* 拖拽上传遮罩 */}
      {dragOver && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-primary-light/70 backdrop-blur-[1px]">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-white text-primary shadow-lg">
            <ImagePlus size={26} />
          </span>
          <p className="text-sm font-semibold text-primary">松开即可添加</p>
          <p className="text-xs text-ink-2">图片将随下一条消息发送；PDF / DOCX / XLSX / MD 自动入库</p>
        </div>
      )}
    </div>
  )
}
