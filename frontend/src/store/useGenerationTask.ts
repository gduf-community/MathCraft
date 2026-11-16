import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '../api/backend'
import { DIFFICULTIES, TYPE_ORDER } from '../constants'

interface PendingGeneration {
  requestId: string
  taskId: string | null
  finished: boolean
  rejected: boolean
  clearing: boolean
  questionIds: string[]
  sessionId: string | null
  body: api.GenerateBody | null
  cleanupCaptured: boolean
}

class GenerationRecoveryError extends Error {}

const storageKey = (userId: string) => `mathcraft-generation:${userId}`
const DELETE_BATCH_SIZE = 200
const delay = () => new Promise<void>(resolve => window.setTimeout(resolve, 500))
const retryable = (error: unknown) => error instanceof TypeError
  || (error instanceof api.ApiError && (error.status === 0 || error.status >= 500))
const rejected = (error: unknown) => error instanceof api.ApiError
  && error.status >= 400 && error.status < 500

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function requestBody(value: unknown): api.GenerateBody | null {
  if (!isRecord(value) || typeof value.bank_id !== 'string'
    || typeof value.document_id !== 'string' || !Array.isArray(value.types)) return null
  const difficulty = DIFFICULTIES.find(item => item === value.difficulty)
  if (!difficulty) return null
  const types: api.GenerateBody['types'] = []
  for (const item of value.types) {
    if (!isRecord(item)) return null
    const type = TYPE_ORDER.find(type => type === item.type)
    if (!type || typeof item.count !== 'number' || !Number.isInteger(item.count) || item.count < 1) return null
    types.push({ type, count: item.count })
  }
  if (value.scope !== undefined && typeof value.scope !== 'string') return null
  if (value.source_mode !== undefined && typeof value.source_mode !== 'string') return null
  if (value.existing_stems !== undefined && (!Array.isArray(value.existing_stems)
    || !value.existing_stems.every((stem: unknown) => typeof stem === 'string'))) return null
  return { bank_id: value.bank_id, document_id: value.document_id, types, difficulty,
    scope: value.scope, source_mode: value.source_mode, existing_stems: value.existing_stems }
}

function readPending(userId: string): PendingGeneration | null {
  const raw = localStorage.getItem(storageKey(userId))
  if (!raw) return null
  let value: unknown
  try { value = JSON.parse(raw) } catch {
    throw new GenerationRecoveryError('本机出题恢复记录已损坏，请使用“重置出题恢复记录”恢复')
  }
  if (!value || typeof value !== 'object' || !('requestId' in value)
    || typeof value.requestId !== 'string'
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.requestId)
    || !('taskId' in value)
    || !(value.taskId === null || typeof value.taskId === 'string')
    || !('finished' in value) || typeof value.finished !== 'boolean'
    || !('rejected' in value) || typeof value.rejected !== 'boolean'
    || !('clearing' in value) || typeof value.clearing !== 'boolean'
    || !('questionIds' in value) || !Array.isArray(value.questionIds)
    || !value.questionIds.every((id: unknown) => typeof id === 'string')
    || !('sessionId' in value) || !(value.sessionId === null || typeof value.sessionId === 'string')) {
    throw new GenerationRecoveryError('本机出题恢复记录不兼容，请使用“重置出题恢复记录”恢复')
  }
  return { requestId: value.requestId, taskId: value.taskId, finished: value.finished,
    rejected: value.rejected, clearing: value.clearing,
    questionIds: value.questionIds, sessionId: value.sessionId,
    body: 'body' in value ? requestBody(value.body) : null,
    cleanupCaptured: 'cleanupCaptured' in value && value.cleanupCaptured === true }
}

/** 持久化任务身份与清理意图，展示版本变化不会终止后台生命周期追踪。 */
export function useGenerationTask(
  userId: string | undefined,
  sessionIsCurrent: () => boolean,
  onDeleted: (ids: string[]) => void,
) {
  const pending = useRef<PendingGeneration | null>(null)
  const loaded = useRef(false)
  const recoveryStarted = useRef(false)
  const clearFlight = useRef<Promise<void> | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generationClearing, setGenerationClearing] = useState(false)
  const [generationRecoveryError, setRecoveryError] = useState<string | null>(null)
  const [genProgress, setProgress] = useState<{ percent: number; stage: string } | null>(null)
  const assertActive = useCallback(() => {
    if (!sessionIsCurrent()) throw new Error('会话已结束，请重新登录后恢复任务')
  }, [sessionIsCurrent])
  const save = useCallback((operation: PendingGeneration | null) => {
    assertActive()
    if (!userId) throw new Error('请先登录')
    if (operation) localStorage.setItem(storageKey(userId), JSON.stringify(operation))
    else localStorage.removeItem(storageKey(userId))
    pending.current = operation
  }, [assertActive, userId])

  const locate = useCallback(async (operation: PendingGeneration) => {
    while (!operation.taskId && !operation.rejected) {
      assertActive()
      try {
        const found = await api.findGenerationRequest(operation.requestId)
        assertActive()
        if (pending.current !== operation) throw new Error('原任务已收尾')
        operation.taskId = found.task_id
        save(operation)
      } catch (error) {
        assertActive()
        if (pending.current !== operation || operation.rejected) return null
        if (!(error instanceof api.ApiError && error.status === 404)) throw error
        if (!operation.body) {
          throw new GenerationRecoveryError('旧出题记录缺少请求参数，无法补发，请使用“重置出题恢复记录”恢复')
        }
        try {
          const started = await api.startGeneration({ ...operation.body, request_id: operation.requestId })
          assertActive()
          if (pending.current !== operation) return null
          operation.taskId = started.task_id
          save(operation)
        } catch (retryError) {
          assertActive()
          if (pending.current !== operation) return null
          if (rejected(retryError)) {
            operation.rejected = true
            operation.finished = true
            save(operation)
            throw retryError
          }
          if (!retryable(retryError)) throw retryError
          await delay()
        }
      }
    }
    return operation.taskId
  }, [assertActive, save])

  const poll = useCallback(async (operation: PendingGeneration, cancel: boolean) => {
    const taskId = await locate(operation)
    if (!taskId || (!cancel && operation.clearing) || pending.current !== operation) return null
    assertActive()
    let state: api.GenerateProgress | null = cancel ? await api.cancelGeneration(taskId) : null
    for (;;) {
      assertActive()
      if (!cancel && operation.clearing) return null
      if (pending.current !== operation) return null
      if (state) {
        operation.questionIds = [...new Set([...operation.questionIds,
          ...(state.question_ids ?? []), ...state.questions.map(q => q.id)])]
        save(operation)
      }
      if (state?.done && state.execution_finished) {
        operation.finished = true
        save(operation)
        return state
      }
      if (state) {
        setProgress({ percent: state.progress, stage: cancel || state.status === 'canceling'
          ? '正在取消，等待后台退出…' : state.stage })
        await delay()
      }
      assertActive()
      if (!cancel && operation.clearing) return null
      try {
        state = await api.getGenerationProgress(taskId)
      } catch (error) {
        assertActive()
        if (pending.current !== operation || (!cancel && operation.clearing)) return null
        if (!retryable(error)) throw error
        setProgress({ percent: 0, stage: '连接中断，正在恢复任务进度…' })
        await delay()
      }
    }
  }, [assertActive, locate, save])

  const clear = useCallback((ids: string[], sessionId: string | null): Promise<void> => {
    if (clearFlight.current) return clearFlight.current
    if (generationRecoveryError) return Promise.reject(new Error(generationRecoveryError))
    const work = async () => {
      assertActive()
      const operation = pending.current ?? { requestId: crypto.randomUUID(), taskId: null,
        rejected: true, finished: true, clearing: true, questionIds: [], sessionId: null,
        body: null, cleanupCaptured: false }
      operation.clearing = true
      operation.questionIds = [...new Set([...operation.questionIds, ...ids])]
      operation.sessionId ??= sessionId
      save(operation)
      setGenerating(true)
      setGenerationClearing(true)
      setProgress({ percent: 0, stage: '正在取消，等待后台退出…' })
      try {
        if (!operation.rejected && !operation.cleanupCaptured) {
          try { await poll(operation, true) } catch (error) {
            if (!operation.rejected) throw error
          }
          assertActive()
          if (pending.current !== operation) throw new Error('原任务已收尾')
          operation.cleanupCaptured = true
          save(operation)
        }
        assertActive()
        setProgress({ percent: 100, stage: '正在清理题目与对话…' })
        while (operation.questionIds.length) {
          const batch = operation.questionIds.slice(0, DELETE_BATCH_SIZE)
          await api.batchDeleteQuestions(batch)
          assertActive()
          onDeleted(batch)
          operation.questionIds = operation.questionIds.slice(batch.length)
          save(operation)
        }
        if (operation.sessionId) {
          try {
            await api.deleteChatSession(operation.sessionId)
          } catch (error) {
            if (!(error instanceof api.ApiError && error.status === 404
              && error.code === 'CHAT_SESSION_NOT_FOUND')) throw error
          }
          assertActive()
          operation.sessionId = null
          save(operation)
        }
        save(null)
        setGenerating(false)
        setGenerationClearing(false)
        setProgress(null)
      } catch (error) {
        if (sessionIsCurrent() && pending.current === operation) {
          if (error instanceof GenerationRecoveryError) setRecoveryError(error.message)
          setProgress({ percent: 0, stage: '清空尚未完成，请再次点击一键清空重试' })
        }
        throw error
      }
    }
    const flight = work().finally(() => { clearFlight.current = null })
    clearFlight.current = flight
    return flight
  }, [assertActive, generationRecoveryError, onDeleted, poll, save, sessionIsCurrent])

  const start = useCallback(async (body: api.GenerateBody) => {
    assertActive()
    if (!userId || !loaded.current || clearFlight.current
      || (pending.current && (!pending.current.finished || pending.current.clearing))) {
      throw new Error('上次出题或清理尚未结束，请等待完成')
    }
    const stored = readPending(userId)
    if (stored && (!stored.finished || stored.clearing)) throw new Error('存在尚未结束的出题，请刷新恢复进度')
    const persistedBody = requestBody(body)
    if (!persistedBody) throw new Error('出题参数无效，请重新选择资料和题型')
    const operation: PendingGeneration = { requestId: crypto.randomUUID(), taskId: null,
      rejected: false, finished: false, clearing: false, questionIds: [], sessionId: null,
      body: persistedBody, cleanupCaptured: false }
    save(operation)
    setGenerating(true)
    setProgress({ percent: 0, stage: '准备生成' })
    try {
      try {
        const started = await api.startGeneration({ ...persistedBody, request_id: operation.requestId })
        assertActive()
        if (pending.current !== operation) return null
        operation.taskId = started.task_id
        save(operation)
      } catch (error) {
        assertActive()
        if (pending.current !== operation) return null
        if (rejected(error)) {
          operation.rejected = true
          operation.finished = true
          save(operation)
          throw error
        }
        if (!retryable(error)) throw error
        if (!operation.clearing) setProgress({ percent: 0, stage: '正在按请求标识恢复任务…' })
      }
      if (operation.clearing) return null
      return await poll(operation, false)
    } catch (error) {
      if (sessionIsCurrent() && pending.current === operation && error instanceof GenerationRecoveryError) {
        setRecoveryError(error.message)
      }
      throw error
    } finally {
      if (sessionIsCurrent() && pending.current === operation && !operation.clearing) {
        setGenerating(!operation.finished)
        setProgress(operation.finished ? null : { percent: 0, stage: '任务状态尚未确认，请一键清空重试查询' })
      }
    }
  }, [assertActive, poll, save, sessionIsCurrent, userId])

  const resetGenerationRecovery = useCallback(() => {
    assertActive()
    if (!generationRecoveryError) return
    save(null)
    loaded.current = true
    setRecoveryError(null)
    setGenerating(false)
    setGenerationClearing(false)
    setProgress(null)
  }, [assertActive, generationRecoveryError, save])

  useEffect(() => {
    if (!userId || recoveryStarted.current) return
    recoveryStarted.current = true
    void (async () => {
      try {
        const operation = readPending(userId)
        pending.current = operation
        loaded.current = true
        if (!operation || (operation.finished && !operation.clearing)) return
        setGenerating(true)
        setProgress({ percent: 0, stage: '正在恢复上次任务…' })
        if (operation.clearing) await clear([], null)
        else {
          await poll(operation, false)
          if (sessionIsCurrent() && pending.current === operation && !operation.clearing) {
            setGenerating(false)
            setProgress(null)
          }
        }
      } catch (error) {
        if (sessionIsCurrent()) {
          console.error('恢复出题任务失败', error)
          if (error instanceof GenerationRecoveryError) setRecoveryError(error.message)
          setGenerating(!!pending.current?.clearing || !pending.current?.rejected)
          setProgress({ percent: 0, stage: '任务恢复失败，请一键清空重试查询' })
        }
      }
    })()
  }, [clear, poll, sessionIsCurrent, userId])

  const isClearing = useCallback(() => pending.current?.clearing ?? false, [])
  return { generating, generationClearing, generationRecoveryError, resetGenerationRecovery,
    genProgress, start, clear, isClearing }
}
