/* global window, localStorage, document */
import assert from 'node:assert/strict'

export async function runChatHistoryCases({ providerCase, selectBank, settleRender }) {
  async function prepare(page) {
    await selectBank(page)
    await page.evaluate(() => window.mergeApp.selectDoc('doc-bank-A'))
    await settleRender(page)
  }
  async function seed(page) {
    await prepare(page)
    await page.evaluate(async () => {
      const h = window.mergeHarness
      h.backend.sendChatMessage = () => h.chatReply({questions:[{id:'preview-result', stem:'合成题'}], batch_id:'preview-batch'})
      await window.mergeApp.sendChat('保留的对话')
      window.mergeApp.selectAll(['preview-result'])
    })
    await page.waitForFunction(() => window.mergeApp.questions.length === 1 && window.mergeApp.selectedIds.length === 1)
  }
  const target = {id:'history-A', title:'历史 A', bankId:'bank-A', docId:'doc-bank-A'}

  for (const mode of ['generate', 'creative', 'qa', 'data']) {
    await providerCase(`history restores server mode ${mode} and continuation/retry never requests an implicit switch`, async page => {
      await prepare(page)
      await page.evaluate(async ({mode, target}) => {
        const h = window.mergeHarness
        h.backend.getChatSession = () => ({mode, messages:[
          {id:'historic-user', role:'user', text:'已有上下文'},
          {id:'historic-answer', role:'assistant', text:'已有回复'},
        ]})
        h.backend.sendChatMessage = () => h.chatReply({mode})
        await window.mergeApp.openSession(target)
      }, {mode, target})
      await page.waitForFunction(mode => !window.mergeApp.sessionLoading && window.mergeApp.mode === mode
        && window.mergeApp.sessionMode === mode, mode)
      assert.equal(await page.evaluate(() => window.mergeApp.modeVisible), false)
      assert.equal(await page.getByRole('group', {name:'对话模式'}).count(), 0)
      await page.getByRole('textbox', {name:'出题消息'}).fill('沿用历史上下文继续')
      await page.getByRole('button', {name:'发送', exact:true}).click()
      await page.waitForFunction(() => !window.mergeApp.botThinking && window.mergeHarness.calls.some(c => c.name === 'sendChatMessage'))
      await page.evaluate(() => window.mergeApp.retryChat('historic-user'))
      await page.waitForFunction(() => !window.mergeApp.botThinking && window.mergeHarness.calls.filter(c => c.name === 'sendChatMessage').length === 2)
      const requests = await page.evaluate(() => window.mergeHarness.calls.filter(c => c.name === 'sendChatMessage').map(c => ({
        sessionId:c.args[0], mode:c.args[5], switchOnly:c.args[6],
      })))
      assert.deepEqual(requests, Array.from({length:2}, () => ({sessionId:target.id, mode, switchOnly:false})))
    })
  }

  await providerCase('empty restored QA session keeps the controller visible with QA selected', async page => {
    await prepare(page)
    await page.evaluate(async target => {
      window.mergeHarness.backend.getChatSession = () => ({mode:'qa', messages:[]})
      await window.mergeApp.openSession(target)
    }, target)
    await page.waitForFunction(() => !window.mergeApp.sessionLoading && window.mergeApp.mode === 'qa')
    assert.equal(await page.getByRole('group', {name:'对话模式'}).isVisible(), true)
    assert.equal(await page.getByRole('button', {name:'知识答疑', exact:true}).getAttribute('aria-pressed'), 'true')
    assert.equal(await page.evaluate(() => window.mergeApp.sessionMode), 'qa')
  })

  await providerCase('history loading guards synchronous context send/retry/edit and UI until questions finish', async page => {
    await prepare(page)
    await page.evaluate(() => window.mergeApp.sendChat('已有消息'))
    await page.waitForFunction(() => window.mergeApp.messages.length === 2)
    await page.evaluate(target => {
      const app = window.mergeApp, h = window.mergeHarness
      h.held.getChatSession = true
      h.held.listQuestions = true
      const messageId = app.messages[0].id
      void app.openSession(target)
      void app.sendChat('不得发送')
      app.retryChat(messageId)
      app.editChat(messageId)
    }, target)
    await page.waitForFunction(() => window.mergeApp.sessionLoading)
    await page.getByRole('textbox', {name:'出题消息'}).fill('加载中草稿')
    assert.equal(await page.getByRole('button', {name:'发送', exact:true}).isDisabled(), true)
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.filter(c => c.name === 'sendChatMessage').length), 1)
    await page.evaluate(() => window.mergeHarness.finish('getChatSession', {mode:'generate', messages:[
      {id:'history-user', role:'user', text:'历史问题'},
      {id:'history-reply', role:'assistant', text:'历史回复', batch_id:'history-batch'},
    ]}))
    await page.waitForFunction(() => window.mergeHarness.pending.listQuestions?.length === 1)
    await page.evaluate(async () => {
      await window.mergeApp.sendChat('仍不得发送')
      window.mergeApp.retryChat('history-user')
    })
    assert.equal(await page.evaluate(() => window.mergeApp.messages.length), 2)
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.filter(c => c.name === 'sendChatMessage').length), 1)
    await page.evaluate(() => window.mergeHarness.finish('listQuestions', {items:[{id:'history-question'}]}))
    await page.waitForFunction(() => !window.mergeApp.sessionLoading)
    await page.evaluate(() => window.mergeApp.sendChat('继续历史会话'))
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.filter(c => c.name === 'sendChatMessage').at(-1).args[0]), target.id)
  })

  for (const phase of ['getChatSession', 'listQuestions']) {
    for (const action of ['openSession', 'selectDoc', 'selectKb', 'startNewChat', 'logout']) {
      await providerCase(`late history ${phase} after ${action} cannot restore previous messages/preview or unlock newer loading`, async page => {
        await prepare(page)
        await page.evaluate(({target, phase}) => {
          const h = window.mergeHarness
          h.backend.getChatSession = () => ({mode:'qa', messages:[{role:'assistant', text:'old history', batch_id:'old-batch'}]})
          h.held[phase] = true
          void window.mergeApp.openSession(target)
        }, {target, phase})
        await page.waitForFunction(phase => window.mergeHarness.pending[phase]?.length === 1, phase)
        await page.evaluate(action => {
          const app = window.mergeApp, h = window.mergeHarness
          if (action === 'openSession') {
            h.held.getChatSession = true
            void app.openSession({id:'history-B', bankId:'bank-B', docId:'doc-bank-B', title:'B'})
          }
          if (action === 'selectDoc') app.selectDoc('doc-other')
          if (action === 'selectKb') app.selectKb('bank-B')
          if (action === 'startNewChat') app.startNewChat()
          if (action === 'logout') h.invalidate()
        }, action)
        await settleRender(page)
        const before = await page.evaluate(() => ({messages:window.mergeApp.messages, questions:window.mergeApp.questions,
          session:window.mergeApp.activeSessionId, loading:window.mergeApp.sessionLoading,
          mode:window.mergeApp.mode, sessionMode:window.mergeApp.sessionMode, modeVisible:window.mergeApp.modeVisible}))
        await page.evaluate(phase => window.mergeHarness.finish(phase,
          phase === 'getChatSession' ? {mode:'qa', messages:[{role:'assistant', text:'late result'}]} : {items:[{id:'late-question'}]}), phase)
        await settleRender(page)
        assert.deepEqual(await page.evaluate(() => ({messages:window.mergeApp.messages, questions:window.mergeApp.questions,
          session:window.mergeApp.activeSessionId, loading:window.mergeApp.sessionLoading,
          mode:window.mergeApp.mode, sessionMode:window.mergeApp.sessionMode, modeVisible:window.mergeApp.modeVisible})), before)
      })
    }
  }

  await providerCase('clear failure preserves preview, selection and chat; async dialog locks, reports failure and retries once', async page => {
    await seed(page)
    const messages = await page.evaluate(() => window.mergeApp.messages)
    await page.evaluate(() => { window.mergeApp.setActiveTab('preview'); window.mergeHarness.held.batchDeleteQuestions = true })
    await page.getByRole('button', {name:'一键清空', exact:true}).click()
    await page.getByRole('button', {name:'确认清空', exact:true}).click()
    await page.waitForFunction(() => window.mergeHarness.pending.batchDeleteQuestions?.length === 1)
    assert.equal(await page.getByRole('dialog').getAttribute('aria-busy'), 'true')
    assert.equal(await page.getByRole('button', {name:'取消', exact:true}).isDisabled(), true)
    await page.evaluate(() => { void window.mergeApp.clearQuestions().catch(() => {}) })
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.filter(c => c.name === 'batchDeleteQuestions').length), 1)
    await page.evaluate(() => window.mergeHarness.pending.batchDeleteQuestions.shift().reject(new Error('合成清空失败')))
    await page.getByRole('alert').filter({hasText:'合成清空失败'}).waitFor()
    assert.equal(await page.evaluate(() => window.mergeApp.questions.length), 1)
    assert.deepEqual(await page.evaluate(() => window.mergeApp.selectedIds), ['preview-result'])
    assert.deepEqual(await page.evaluate(() => window.mergeApp.messages), messages)
    await page.getByRole('button', {name:'确认清空', exact:true}).click()
    await page.waitForFunction(() => window.mergeHarness.pending.batchDeleteQuestions.length === 1)
    await page.evaluate(() => window.mergeHarness.finish('batchDeleteQuestions'))
    await page.waitForFunction(() => !document.querySelector('[role=dialog]'))
    assert.equal(await page.evaluate(() => window.mergeApp.questions.length), 0)
    assert.deepEqual(await page.evaluate(() => window.mergeApp.messages), messages)
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.some(c => c.name === 'deleteChatSession')), false)
  })

  await providerCase('running chat blocks clear at button and context and keeps messages', async page => {
    await seed(page)
    await page.evaluate(() => {
      window.mergeHarness.held.sendChatMessage = true
      void window.mergeApp.sendChat('正在处理')
      window.mergeApp.setActiveTab('preview')
    })
    await page.waitForFunction(() => window.mergeApp.botThinking)
    assert.equal(await page.getByRole('button', {name:'一键清空', exact:true}).isDisabled(), true)
    const error = await page.evaluate(async () => {
      try { await window.mergeApp.clearQuestions() } catch (error) { return error.message }
    })
    assert.match(error, /正在处理中/)
    assert.equal(await page.evaluate(() => window.mergeApp.questions.length), 1)
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.some(c => c.name === 'batchDeleteQuestions')), false)
  })

  await providerCase('pause waits for server and restores a committed batch before clear', async page => {
    await seed(page)
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.held.sendChatMessage = h.held.cancelChat = h.held.getChatTurn = true
      void window.mergeApp.sendChat('等待生成结果')
    })
    await page.waitForFunction(() => window.mergeHarness.pending.sendChatMessage?.length === 1)
    await page.getByRole('button', {name:'暂停', exact:true}).click()
    assert.equal(await page.getByRole('button', {name:'正在暂停', exact:true}).isDisabled(), true)
    assert.equal(await page.getByRole('button', {name:'正在暂停', exact:true}).locator('svg').count(), 1)
    await page.evaluate(() => window.mergeApp.setActiveTab('preview'))
    assert.equal(await page.getByRole('button', {name:'一键清空', exact:true}).isDisabled(), true)
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.finish('cancelChat', {status:'done', execution_finished:false, batch_id:'late', result:null})
    })
    await page.waitForFunction(() => window.mergeHarness.pending.getChatTurn?.length === 1)
    assert.equal(await page.getByRole('button', {name:'一键清空', exact:true}).isDisabled(), true)
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.finish('getChatTurn', {status:'done', execution_finished:true, batch_id:'late',
        result:h.chatReply({reply:'已完成该轮', batch_id:'late', questions:[{id:'late-question'}]})})
    })
    await page.waitForFunction(() => !window.mergeApp.botThinking
      && window.mergeApp.questions.some(question => question.id === 'late-question'))
    await page.getByRole('button', {name:'一键清空', exact:true}).click()
    await page.getByRole('button', {name:'确认清空', exact:true}).click()
    await page.waitForFunction(() => window.mergeApp.questions.length === 0)
    assert.equal(await page.evaluate(() => window.mergeApp.messages.some(m => m.text === '已完成该轮')), true)
    assert.equal(await page.evaluate(() => window.mergeHarness.calls
      .some(call => call.name === 'batchDeleteQuestions' && call.args[0].includes('late-question'))), true)
  })

  await providerCase('failed pause stays locked and refresh continues the original request', async page => {
    await seed(page)
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.held.sendChatMessage = h.held.cancelChat = true
      void window.mergeApp.sendChat('等待暂停确认')
    })
    await page.waitForFunction(() => window.mergeHarness.pending.sendChatMessage?.length === 1)
    await page.getByRole('button', {name:'暂停', exact:true}).click()
    await page.waitForFunction(() => window.mergeHarness.pending.cancelChat?.length === 1)
    await page.evaluate(() => window.mergeHarness.pending.cancelChat.shift().reject(new Error('断连')))
    await page.getByRole('button', {name:'重试暂停', exact:true}).waitFor()
    await page.evaluate(() => window.mergeApp.setActiveTab('preview'))
    assert.equal(await page.getByRole('button', {name:'一键清空', exact:true}).isDisabled(), true)
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.backend.latestBatch = () => ({batch_id:'preview-batch', questions:[{id:'preview-result'}]})
      h.generation += 1
      window.remountMerge()
    })
    await page.waitForFunction(() => window.mergeHarness.pending.cancelChat?.length === 1)
    const requestIds = await page.evaluate(() => ({
      sent: window.mergeHarness.calls.filter(call => call.name === 'sendChatMessage').at(-1).args[7],
      paused: window.mergeHarness.calls.filter(call => call.name === 'cancelChat').map(call => call.args[1]),
    }))
    assert.deepEqual(requestIds.paused, [requestIds.sent, requestIds.sent])
    await page.evaluate(() => window.mergeHarness.finish('cancelChat', {
      status:'canceled', execution_finished:true, batch_id:null, result:null,
    }))
    await page.waitForFunction(() => !window.mergeApp.botThinking && window.mergeApp.chatPauseStatus === null)
    assert.equal(await page.evaluate(() => window.mergeApp.questions[0]?.id), 'preview-result')
    assert.equal(await page.evaluate(() => window.mergeApp.docs.some(doc => doc.id === 'doc-bank-A')), true)
  })

  await providerCase('preview clear batches at 200; partial failure keeps all local questions and favorites until retry succeeds', async page => {
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.favoriteRows = [{id:'preview-0'}, {id:'keep-favorite'}]
      h.generation++
      window.remountMerge()
    })
    await page.waitForFunction(() => window.mergeApp.favorites.length === 2)
    await prepare(page)
    await page.evaluate(async () => {
      const h = window.mergeHarness
      h.backend.sendChatMessage = () => h.chatReply({questions:Array.from({length:401}, (_, i) => ({id:`preview-${i}`}))})
      await window.mergeApp.sendChat('合成大批题目')
      h.batchCount = 0
      h.backend.batchDeleteQuestions = () => { if (++h.batchCount === 2) throw new Error('synthetic batch failure') }
    })
    await page.waitForFunction(() => window.mergeApp.questions.length === 401)
    await page.evaluate(async () => {
      try { await window.mergeApp.clearQuestions() } catch (error) { window.mergeHarness.clearError = error.message }
    })
    assert.equal(await page.evaluate(() => window.mergeApp.questions.length), 401)
    assert.equal(await page.evaluate(() => window.mergeApp.favorites.length), 2)
    await page.evaluate(() => window.mergeApp.clearQuestions())
    await page.waitForFunction(() => window.mergeApp.questions.length === 0)
    assert.deepEqual(await page.evaluate(() => window.mergeApp.favorites.map(q => q.id)), ['keep-favorite'])
    assert.deepEqual(await page.evaluate(() => window.mergeHarness.calls.filter(c => c.name === 'batchDeleteQuestions').map(c => c.args[0].length)), [200,200,200,200,1])
  })

  await providerCase('clear invalidates delayed document preview but does not invalidate current conversation', async page => {
    await seed(page)
    const messages = await page.evaluate(() => window.mergeApp.messages)
    await page.evaluate(() => {
      window.mergeHarness.held.latestBatch = true
      window.mergeApp.selectDoc('doc-bank-A')
    })
    await page.waitForFunction(() => window.mergeHarness.pending.latestBatch?.length === 1)
    await page.evaluate(() => window.mergeApp.clearQuestions())
    await page.evaluate(() => window.mergeHarness.finish('latestBatch', {batch_id:'stale', questions:[{id:'stale'}]}))
    await settleRender(page)
    assert.equal(await page.evaluate(() => window.mergeApp.questions.length), 0)
    assert.deepEqual(await page.evaluate(() => window.mergeApp.messages), messages)
  })

  for (const action of ['openSession', 'selectDoc', 'logout']) {
    await providerCase(`clear completion after ${action} cannot erase a newer preview or dialogue`, async page => {
      await seed(page)
      await page.evaluate(() => {
        window.mergeHarness.held.batchDeleteQuestions = true
        void window.mergeApp.clearQuestions()
      })
      await page.waitForFunction(() => window.mergeHarness.pending.batchDeleteQuestions?.length === 1)
      await page.evaluate(async ({action, target}) => {
        const app = window.mergeApp, h = window.mergeHarness
        if (action === 'openSession') {
          h.backend.getChatSession = () => ({mode:'qa', messages:[{role:'assistant', text:'new session', batch_id:'new-batch'}]})
          h.backend.listQuestions = () => ({items:[{id:'new-question'}]})
          await app.openSession(target)
        }
        if (action === 'selectDoc') {
          h.backend.latestBatch = () => ({batch_id:'new-batch', questions:[{id:'new-question'}]})
          app.selectDoc('doc-other')
        }
        if (action === 'logout') h.invalidate()
      }, {action, target})
      await settleRender(page)
      const before = await page.evaluate(() => ({questions:window.mergeApp.questions, messages:window.mergeApp.messages}))
      await page.evaluate(() => window.mergeHarness.finish('batchDeleteQuestions'))
      await settleRender(page)
      assert.deepEqual(await page.evaluate(() => ({questions:window.mergeApp.questions, messages:window.mergeApp.messages})), before)
    })
  }

  await providerCase('history deletion awaits server; failure keeps list and dialog; older list cannot resurrect deletion', async page => {
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.sessions = [{session_id:'history-A', title:'历史 A', bank_id:'bank-A', document_id:'doc-bank-A'}]
      h.generation++
      window.remountMerge()
    })
    await page.waitForFunction(() => window.mergeApp.sessions.length === 1)
    await prepare(page)
    await page.evaluate(async () => {
      const h = window.mergeHarness
      h.held.listChatSessions = true
      h.held.deleteChatSession = true
      await window.mergeApp.sendChat('刷新历史列表')
    })
    await page.getByTitle('历史 A（右键删除）').click({button:'right'})
    await page.getByRole('button', {name:'确认删除', exact:true}).click()
    await page.waitForFunction(() => window.mergeHarness.pending.deleteChatSession?.length === 1)
    assert.equal(await page.getByRole('dialog').getAttribute('aria-busy'), 'true')
    assert.equal(await page.evaluate(() => window.mergeApp.sessions.length), 1)
    await page.evaluate(() => window.mergeHarness.pending.deleteChatSession.shift().reject(new Error('合成删除失败')))
    await page.getByRole('alert').filter({hasText:'合成删除失败'}).waitFor()
    assert.equal(await page.evaluate(() => window.mergeApp.sessions.length), 1)
    await page.getByRole('button', {name:'确认删除', exact:true}).click()
    await page.waitForFunction(() => window.mergeHarness.pending.deleteChatSession.length === 1)
    await page.evaluate(() => window.mergeHarness.finish('deleteChatSession'))
    await page.waitForFunction(() => window.mergeApp.sessions.length === 0)
    await page.evaluate(() => {
      const h = window.mergeHarness
      while (h.pending.listChatSessions.length) h.finish('listChatSessions', h.sessions)
    })
    await settleRender(page)
    assert.equal(await page.evaluate(() => window.mergeApp.sessions.length), 0)
  }, 'history')

  await providerCase('saved task cleanup failure keeps an actionable retry in the agent tabs without restoring the quick panel', async page => {
    await page.evaluate(() => {
      const h = window.mergeHarness
      localStorage.setItem('mathcraft-generation:A', JSON.stringify({
        requestId:'11111111-1111-4111-8111-111111111111', taskId:null, finished:true,
        rejected:true, clearing:true, questionIds:['legacy-result'], sessionId:'legacy-session',
      }))
      h.held.batchDeleteQuestions = true
      h.generation++
      window.remountMerge()
    })
    await page.waitForFunction(() => window.mergeHarness.pending.batchDeleteQuestions?.length === 1)
    await page.evaluate(() => window.mergeHarness.pending.batchDeleteQuestions.shift().reject(new Error('synthetic legacy cleanup failure')))
    await page.getByRole('button', {name:'继续清理历史任务', exact:true}).click()
    await page.getByRole('button', {name:'继续清理', exact:true}).click()
    await page.waitForFunction(() => window.mergeHarness.pending.batchDeleteQuestions.length === 1)
    assert.equal(await page.getByRole('dialog').getAttribute('aria-busy'), 'true')
    await page.evaluate(() => window.mergeHarness.finish('batchDeleteQuestions'))
    await page.waitForFunction(() => !window.mergeApp.generating && localStorage.getItem('mathcraft-generation:A') === null)
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.find(c => c.name === 'deleteChatSession').args[0]), 'legacy-session')
    assert.equal(await page.getByRole('button', {name:'新建对话', exact:true}).isVisible(), true)
  })
}

export async function runGenerationTaskCases({providerCase, settleRender}) {
  const body = {bank_id:'bank-A', document_id:'doc-bank-A', types:[{type:'single', count:1}], difficulty:'中'}
  const done = {done:true, execution_finished:true, status:'canceled', progress:0, stage:'已退出', questions:[], question_ids:[], error:null}
  const persisted = (overrides = {}) => ({requestId:'11111111-1111-4111-8111-111111111111', taskId:'persisted-task',
    finished:false, rejected:false, clearing:true, questionIds:[], sessionId:null, body, ...overrides})
  const taskCase = (name, run) => providerCase(name, run, 'task')

  await taskCase('task identity: delayed POST cannot unlock next operation; cleanup waits for execution_finished', async page => {
    await page.evaluate(body => {
      const h = window.mergeHarness
      h.held.startGeneration = true
      h.held.cancelGeneration = true
      h.held.getGenerationProgress = true
      void window.generationTask.start(body).catch(error => { h.startError = error.message })
    }, body)
    await page.waitForFunction(() => window.mergeHarness.pending.startGeneration?.length === 1)
    const requestId = await page.evaluate(() => window.mergeHarness.pending.startGeneration[0].args[0].request_id)
    assert.match(requestId, /^[a-f0-9-]{36}$/)
    await page.evaluate(() => { void window.generationTask.clear([], null) })
    await page.waitForFunction(() => window.mergeHarness.pending.cancelGeneration?.length === 1)
    assert.equal(await page.evaluate(async body => {
      try { await window.generationTask.start(body); return false } catch { return true }
    }, body), true)
    await page.evaluate(done => window.mergeHarness.finish('cancelGeneration', {...done, done:true, execution_finished:false}), done)
    await page.waitForFunction(() => window.mergeHarness.pending.getGenerationProgress?.length === 1)
    assert.equal(await page.evaluate(() => window.generationTask.generating), true)
    await page.evaluate(done => window.mergeHarness.finish('getGenerationProgress', done), done)
    await page.waitForFunction(() => !window.generationTask.generating)
    await page.evaluate(body => { void window.generationTask.start(body) }, body)
    await page.waitForFunction(() => window.mergeHarness.pending.startGeneration.length === 2)
    const next = await page.evaluate(() => JSON.parse(localStorage.getItem('mathcraft-generation:A')).requestId)
    assert.notEqual(next, requestId)
    await page.evaluate(() => window.mergeHarness.finish('startGeneration', {task_id:'old-task'}))
    await settleRender(page)
    assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('mathcraft-generation:A')).requestId), next)
    assert.equal(await page.evaluate(() => window.generationTask.generating), true)
  })

  for (const replayStatus of [null, 403, 409, 422]) {
    await taskCase(`task recovery: lost start uses identical UUID and parameters; replay status ${replayStatus}`, async page => {
      await page.evaluate(({body, replayStatus}) => {
        const h = window.mergeHarness
        h.attempts = 0
        h.backend.startGeneration = () => {
          if (++h.attempts === 1) throw new TypeError('synthetic lost start')
          if (replayStatus) throw new window.mergeApiError('synthetic rejection', 'REJECTED', replayStatus)
          return {task_id:'replayed-task'}
        }
        h.backend.findGenerationRequest = () => { throw new window.mergeApiError('not accepted', 'NOT_FOUND', 404) }
        h.held.getGenerationProgress = true
        void window.generationTask.start(body).catch(error => { h.startError = error.message })
      }, {body, replayStatus})
      await page.waitForFunction(status => status ? !!window.mergeHarness.startError : window.mergeHarness.pending.getGenerationProgress?.length === 1, replayStatus)
      const calls = await page.evaluate(() => window.mergeHarness.calls.filter(c => c.name === 'startGeneration').map(c => c.args[0]))
      assert.equal(calls.length, 2)
      assert.deepEqual(calls[0], calls[1])
      if (replayStatus) {
        assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('mathcraft-generation:A')).rejected), true)
      }
      await page.evaluate(() => window.generationTask.clear([], null))
      assert.equal(await page.evaluate(() => localStorage.getItem('mathcraft-generation:A')), null)
    })
  }

  for (const cancelDone of [true, false]) {
    await taskCase(`task cleanup: authoritative survivor IDs with empty questions, cancellation done=${cancelDone}, failed batch retries remainder`, async page => {
      const ids = Array.from({length:401}, (_, i) => `result-${i}`)
      await page.evaluate(({operation, done, cancelDone, ids}) => {
        const h = window.mergeHarness
        localStorage.setItem('mathcraft-generation:A', JSON.stringify(operation))
        h.backend.cancelGeneration = () => ({...done, done:cancelDone, execution_finished:cancelDone, question_ids:ids})
        h.backend.getGenerationProgress = () => done
        h.deleteCalls = 0
        h.backend.batchDeleteQuestions = () => { if (++h.deleteCalls === 2) throw new Error('synthetic second batch failure') }
        h.generation++
        window.remountMerge()
      }, {operation:persisted(), done, cancelDone, ids})
      await page.waitForFunction(() => window.mergeHarness.deleteCalls === 2)
      await settleRender(page)
      assert.deepEqual(await page.evaluate(() => window.mergeHarness.deletedIds), ids.slice(0,200))
      assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('mathcraft-generation:A')).questionIds), ids.slice(200))
      assert.equal(await page.evaluate(() => window.generationTask.generating), true)
      await page.evaluate(() => window.generationTask.clear([], null))
      assert.deepEqual(await page.evaluate(() => window.mergeHarness.deletedIds), ids)
      assert.equal(await page.evaluate(() => localStorage.getItem('mathcraft-generation:A')), null)
      assert.equal(await page.evaluate(() => window.mergeHarness.calls.filter(c => c.name === 'cancelGeneration').length), 1)
    })
  }

  await taskCase('task recovery scopes pending cleanup and delete callbacks to the original account across remount', async page => {
    await page.evaluate(operation => {
      const h = window.mergeHarness
      localStorage.setItem('mathcraft-generation:A', JSON.stringify(operation))
      h.held.cancelGeneration = true
      h.generation++
      window.remountMerge()
    }, persisted({questionIds:['saved-result'], sessionId:'saved-session'}))
    await page.waitForFunction(() => window.mergeHarness.pending.cancelGeneration?.length === 1)
    await page.evaluate(done => {
      const h = window.mergeHarness
      h.user = {...h.user, userId:'B'}
      h.generation++
      window.remountMerge()
      h.finish('cancelGeneration', done)
    }, done)
    await settleRender(page)
    assert.deepEqual(await page.evaluate(() => window.mergeHarness.deletedIds), [])
    assert.notEqual(await page.evaluate(() => localStorage.getItem('mathcraft-generation:A')), null)
    await page.evaluate(() => {
      const h = window.mergeHarness
      h.user = {...h.user, userId:'A'}
      h.generation++
      h.held.cancelGeneration = false
      window.remountMerge()
    })
    await page.waitForFunction(() => localStorage.getItem('mathcraft-generation:A') === null)
    assert.deepEqual(await page.evaluate(() => window.mergeHarness.deletedIds), ['saved-result'])
    assert.equal(await page.evaluate(() => window.mergeHarness.calls.find(c => c.name === 'deleteChatSession').args[0]), 'saved-session')
  })

  for (const kind of ['broken-json', 'incompatible', 'legacy-without-body']) {
    await taskCase(`task recovery: ${kind} requires explicit reset and preserves the busy gate`, async page => {
      await page.evaluate(({kind, operation}) => {
        const h = window.mergeHarness
        localStorage.setItem('mathcraft-generation:A', kind === 'broken-json' ? '{' : kind === 'incompatible' ? '{}' : JSON.stringify(operation))
        h.backend.findGenerationRequest = () => { throw new window.mergeApiError('not found', 'NOT_FOUND', 404) }
        h.generation++
        window.remountMerge()
      }, {kind, operation:persisted({taskId:null, body:null})})
      await page.waitForFunction(() => !!window.generationTask.generationRecoveryError)
      assert.equal(await page.evaluate(() => window.generationTask.generating), true)
      await page.getByRole('button', {name:'重置恢复记录', exact:true}).click()
      await page.getByRole('button', {name:'确定', exact:true}).click()
      await page.waitForFunction(() => !window.generationTask.generationRecoveryError && !window.generationTask.generating)
      assert.equal(await page.evaluate(() => localStorage.getItem('mathcraft-generation:A')), null)
    })
  }

  for (const remount of [true, false]) {
    await taskCase(`task cleanup: lost session DELETE accepts only CHAT_SESSION_NOT_FOUND after ${remount ? 'reload' : 'retry'}`, async page => {
      await page.evaluate(async () => {
        const h = window.mergeHarness
        h.backend.deleteChatSession = () => { throw new TypeError('synthetic lost delete') }
        try { await window.generationTask.clear([], 'saved-session') } catch (error) { h.clearError = error.message }
      })
      assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('mathcraft-generation:A')).sessionId), 'saved-session')
      await page.evaluate(async remount => {
        const h = window.mergeHarness
        h.backend.deleteChatSession = () => { throw new window.mergeApiError('gone', 'CHAT_SESSION_NOT_FOUND', 404) }
        if (remount) { h.generation++; window.remountMerge() }
        else await window.generationTask.clear([], null)
      }, remount)
      await page.waitForFunction(() => localStorage.getItem('mathcraft-generation:A') === null)
      assert.equal(await page.evaluate(() => window.mergeHarness.calls.filter(c => c.name === 'deleteChatSession').length), 2)
    })
  }

  await taskCase('task cleanup: unrelated 404 preserves session identity and busy gate for retry', async page => {
    await page.evaluate(async () => {
      const h = window.mergeHarness
      h.backend.deleteChatSession = () => { throw new window.mergeApiError('wrong resource', 'BANK_NOT_FOUND', 404) }
      try { await window.generationTask.clear([], 'saved-session') } catch (error) { h.clearError = error.code }
    })
    assert.equal(await page.evaluate(() => window.mergeHarness.clearError), 'BANK_NOT_FOUND')
    assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('mathcraft-generation:A')).sessionId), 'saved-session')
    assert.equal(await page.evaluate(() => window.generationTask.generating), true)
    await page.evaluate(async () => {
      window.mergeHarness.backend.deleteChatSession = () => {}
      await window.generationTask.clear([], null)
    })
    assert.equal(await page.evaluate(() => localStorage.getItem('mathcraft-generation:A')), null)
  })
}
