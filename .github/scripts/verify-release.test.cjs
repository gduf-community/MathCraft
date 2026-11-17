const assert = require('node:assert/strict')
const { test } = require('node:test')
const verifyRelease = require('./verify-release.cjs')
const requireCodeQLAnalyses = require('./verify-codeql.cjs')

const SHA = 'a'.repeat(40)
const NAMES = {
  10: ['Backend lint, types and tests', 'Frontend lint, types, build and regressions'],
  20: ['Analyze (actions)', 'Analyze (javascript-typescript)', 'Analyze (python)',
    'CodeQL required'],
}

function fixture(branch = 'main') {
  const runs = [
    { id: 10, path: '.github/workflows/checks.yml', event: 'push' },
    { id: 20, path: '.github/workflows/codeql.yml', event: 'push' },
  ].map(run => ({
    ...run, head_sha: SHA, head_branch: branch, run_attempt: 1,
    head_repository: { full_name: 'example/project' },
    status: 'completed', conclusion: 'success', html_url: `https://example.test/${run.id}`,
  }))
  const jobs = Object.fromEntries(Object.entries(NAMES).map(([id, names]) => [id,
    names.map(name => ({ name, head_sha: SHA, run_attempt: 1,
      status: 'completed', conclusion: 'success' })),
  ]))
  const analyses = ['actions', 'javascript-typescript', 'python'].map((language, index) => ({
    id: 100 + index, ref: `refs/heads/${branch}`, commit_sha: SHA,
    tool: { name: 'CodeQL' }, analysis_key: '.github/workflows/codeql.yml:analyze',
    category: `/language:${language}`, error: '',
  }))
  const outputs = {}
  const requests = []
  const state = { runs, jobs, analyses, outputs, requests, current: run => run }
  const actions = {
    listWorkflowRunsForRepo: 'runs', listJobsForWorkflowRun: 'jobs',
    getWorkflowRun: async ({ run_id }) => ({
      data: state.current(state.runs.find(run => run.id === run_id)),
    }),
  }
  const summary = {
    addHeading() { return this }, addRaw() { return this }, async write() {},
  }
  state.args = {
    context: { repo: { owner: 'example', repo: 'project' }, sha: SHA,
      ref: `refs/heads/${branch}`, eventName: 'workflow_dispatch' },
    core: { info() {}, setOutput(name, value) { outputs[name] = value }, summary },
    github: {
      rest: { actions, codeScanning: { listRecentAnalyses: 'analyses' } },
      async paginate(endpoint, params) {
        requests.push([endpoint, params])
        if (state.error) throw state.error
        if (endpoint === 'analyses') {
          if (state.analysisError) throw state.analysisError
          return structuredClone(state.analyses)
        }
        return structuredClone(endpoint === 'runs' ? state.runs : state.jobs[params.run_id])
      },
    },
  }
  return state
}

for (const branch of ['main', 'agent']) {
  test(`允许 ${branch} 同提交的完整成功检查`, async () => {
    const state = fixture(branch)
    await verifyRelease(state.args)
    assert.deepEqual(state.outputs, { sha: SHA })
    assert.deepEqual(state.requests[0], ['runs', {
      owner: 'example', repo: 'project', branch, head_sha: SHA, per_page: 100,
    }])
    assert.equal(state.requests[1][1].filter, 'all')
    const analysisIndex = state.requests.findIndex(([endpoint]) => endpoint === 'analyses')
    assert.deepEqual(state.requests[analysisIndex], ['analyses', {
      owner: 'example', repo: 'project', ref: `refs/heads/${branch}`,
      tool_name: 'CodeQL', per_page: 100,
    }])
    assert.deepEqual(state.requests.slice(0, analysisIndex).map(([endpoint]) => endpoint),
      ['runs', 'jobs', 'jobs'])
    assert.equal(state.requests[analysisIndex + 1][0], 'runs')
  })
}

for (const ref of ['refs/heads/feature', 'refs/tags/main', 'refs/pull/21/merge']) {
  test(`拒绝非长期分支 ${ref}`, async () => {
    const state = fixture()
    state.args.context.ref = ref
    await assert.rejects(verifyRelease(state.args), /仅允许手动发布/)
    assert.equal(state.requests.length, 0)
  })
}

test('拒绝非手动触发和非法提交标识', async () => {
  const state = fixture()
  state.args.context.eventName = 'push'
  await assert.rejects(verifyRelease(state.args), /仅允许手动发布/)
  state.args.context.eventName = 'workflow_dispatch'
  state.args.context.sha = 'main'
  await assert.rejects(verifyRelease(state.args), /仅允许手动发布/)
})

for (const change of [
  { head_sha: 'b'.repeat(40) }, { head_branch: 'agent' },
  { event: 'pull_request' }, { path: '.github/workflows/fake.yml' },
  { head_repository: { full_name: 'other/fork' } },
]) {
  test(`其他提交、分支、PR、工作流或仓库不能替代检查 ${JSON.stringify(change)}`, async () => {
    const state = fixture()
    Object.assign(state.runs[0], change)
    await assert.rejects(verifyRelease(state.args), /缺少/)
    assert.deepEqual(state.outputs, {})
  })
}

test('CodeQL 缺失不放行', async () => {
  const state = fixture()
  state.runs.pop()
  await assert.rejects(verifyRelease(state.args), /CodeQL 缺少/)
  assert.deepEqual(state.outputs, {})
})

for (const change of [
  { path: 'dynamic/github-code-scanning/codeql', event: 'dynamic' },
  { path: 'dynamic/github-code-scanning/codeql', event: 'push' },
  { event: 'pull_request' }, { event: 'schedule' }, { event: 'dynamic' },
]) {
  test(`CodeQL 非可信路径或事件成功不能放行 ${JSON.stringify(change)}`, async () => {
    const state = fixture()
    Object.assign(state.runs[1], change)
    await assert.rejects(verifyRelease(state.args), /CodeQL 缺少/)
    assert.deepEqual(state.outputs, {})
  })
}

for (const branch of ['main', 'agent']) {
  test(`允许 ${branch} 同提交的 CodeQL 手动检查成功发布`, async () => {
    const state = fixture(branch)
    state.runs[1].event = 'workflow_dispatch'
    await verifyRelease(state.args)
    assert.deepEqual(state.outputs, { sha: SHA })
  })
}

for (const [status, conclusion] of [
  ['completed', 'failure'], ['completed', 'cancelled'], ['completed', 'skipped'],
  ['completed', 'neutral'], ['completed', 'timed_out'], ['queued', null],
  ['in_progress', null], ['waiting', null],
]) {
  test(`较新的 ${status}/${conclusion} 覆盖旧成功记录`, async () => {
    const state = fixture()
    state.runs.push({ ...state.runs[0], id: 11, status, conclusion })
    await assert.rejects(verifyRelease(state.args), /最新运行 #11 尚未通过/)
    assert.deepEqual(state.outputs, {})
  })
}

test('较旧运行的重跑成功不能覆盖较新失败', async () => {
  const state = fixture()
  state.runs[0].run_attempt = 5
  state.runs.push({ ...state.runs[0], id: 11, run_attempt: 1, conclusion: 'failure' })
  await assert.rejects(verifyRelease(state.args), /最新运行 #11 尚未通过/)
})

test('新的完整成功可以替代旧失败', async () => {
  const state = fixture()
  state.runs.push({ ...state.runs[0], id: 9, conclusion: 'failure' })
  await verifyRelease(state.args)
  assert.equal(state.outputs.sha, SHA)
})

for (const id of [10, 20]) {
  for (const conclusion of ['skipped', 'failure', 'neutral', 'cancelled']) {
    test(`工作流 ${id} 整体成功不能掩盖必需任务 ${conclusion}`, async () => {
      const state = fixture()
      state.jobs[id][0].conclusion = conclusion
      await assert.rejects(verifyRelease(state.args), /必需任务/)
    })
  }
  test(`工作流 ${id} 任务缺失不放行`, async () => {
    const state = fixture()
    state.jobs[id] = []
    await assert.rejects(verifyRelease(state.args), /必需任务/)
  })
}

test('只重跑失败任务时复用其他任务最近一次成功', async () => {
  const state = fixture()
  state.runs[0].run_attempt = 2
  state.jobs[10][1].conclusion = 'failure'
  state.jobs[10].push({ ...state.jobs[10][1], run_attempt: 2, conclusion: 'success' })
  await verifyRelease(state.args)
  assert.equal(state.outputs.sha, SHA)
})

test('新 attempt 失败不能使用该任务的旧成功', async () => {
  const state = fixture()
  state.runs[0].run_attempt = 2
  state.jobs[10].push({ ...state.jobs[10][1], run_attempt: 2, conclusion: 'failure' })
  await assert.rejects(verifyRelease(state.args), /必需任务/)
})

test('同 attempt 重名任务和其他提交的任务均拒绝', async () => {
  const state = fixture()
  state.jobs[10].push({ ...state.jobs[10][0] })
  await assert.rejects(verifyRelease(state.args), /必需任务/)
  state.jobs[10].pop()
  state.jobs[10][0].head_sha = 'b'.repeat(40)
  await assert.rejects(verifyRelease(state.args), /必需任务/)
})

for (const change of [
  { run_attempt: 2 }, { status: 'in_progress', conclusion: null },
  { conclusion: 'failure' }, { head_sha: 'b'.repeat(40) },
]) {
  test(`校验期间检查被重跑或改变则拒绝 ${JSON.stringify(change)}`, async () => {
    const state = fixture()
    state.current = run => ({ ...run, ...change })
    await assert.rejects(verifyRelease(state.args), /检查状态已变化/)
    assert.deepEqual(state.outputs, {})
  })
}

test('API 权限或网络异常不能放行', async () => {
  const state = fixture()
  state.error = new Error('fixture API forbidden')
  await assert.rejects(verifyRelease(state.args), /API forbidden/)
  assert.deepEqual(state.outputs, {})
})

for (const id of [10, 20]) {
  for (const [status, conclusion] of [
    ['queued', null], ['completed', 'failure'], ['completed', 'success'],
  ]) {
    test(`查询后新增工作流 ${id} 的 ${status}/${conclusion} 运行必须重新验证`, async () => {
      const state = fixture()
      const paginate = state.args.github.paginate
      state.args.github.paginate = async (endpoint, params) => {
        const result = await paginate(endpoint, params)
        if (endpoint === 'jobs' && params.run_id === id) {
          const run = state.runs.find(candidate => candidate.id === id)
          state.runs.push({ ...run, id: id + 1, status, conclusion })
        }
        return result
      }
      await assert.rejects(verifyRelease(state.args), /检查状态已变化/)
      assert.deepEqual(state.outputs, {})
    })
  }
}

for (const phase of ['jobs', 'run']) {
  test(`校验 CodeQL 的 ${phase} 期间 Code checks 开始重跑必须拒绝`, async () => {
    const state = fixture()
    const startRerun = () => {
      state.runs[0] = { ...state.runs[0], run_attempt: 2,
        status: 'in_progress', conclusion: null }
    }
    if (phase === 'jobs') {
      const paginate = state.args.github.paginate
      state.args.github.paginate = async (endpoint, params) => {
        const result = await paginate(endpoint, params)
        if (endpoint === 'jobs' && params.run_id === 20) startRerun()
        return result
      }
    } else {
      state.current = run => {
        if (run.id === 20) startRerun()
        return run
      }
    }
    await assert.rejects(verifyRelease(state.args), /检查状态已变化/)
    assert.deepEqual(state.outputs, {})
  })
}

for (const id of [10, 20]) {
  test(`最终列表返回后工作流 ${id} 开始重跑仍须拒绝`, async () => {
    const state = fixture()
    const paginate = state.args.github.paginate
    let queries = 0
    state.args.github.paginate = async (endpoint, params) => {
      const result = await paginate(endpoint, params)
      if (endpoint === 'runs' && ++queries === 2) {
        const index = state.runs.findIndex(run => run.id === id)
        state.runs[index] = { ...state.runs[index], run_attempt: 2,
          status: 'in_progress', conclusion: null }
      }
      return result
    }
    await assert.rejects(verifyRelease(state.args), /检查状态已变化/)
    assert.deepEqual(state.outputs, {})
  })
}

test('所有 jobs 成功但 CodeQL 分析记录为空仍拒绝发布', async () => {
  const state = fixture()
  state.analyses = []
  await assert.rejects(verifyRelease(state.args), /CodeQL 分析 actions 缺失或处理失败/)
  assert.deepEqual(state.outputs, {})
})

for (const language of ['actions', 'javascript-typescript', 'python']) {
  test(`所有 jobs 成功但缺少 ${language} 分析仍拒绝发布`, async () => {
    const state = fixture()
    state.analyses = state.analyses.filter(analysis => analysis.category !== `/language:${language}`)
    await assert.rejects(verifyRelease(state.args), new RegExp(`CodeQL 分析 ${language} 缺失`))
    assert.deepEqual(state.outputs, {})
  })
}

for (const change of [
  { commit_sha: 'b'.repeat(40) }, { ref: 'refs/heads/agent' },
  { analysis_key: 'dynamic/github-code-scanning/codeql:analyze' },
  { analysis_key: '.github/workflows/codeql.yml:other' },
  { tool: { name: 'Other' } }, { tool: null }, { category: '/language:other' },
]) {
  test(`CodeQL 分析不匹配提交、引用或来源必须拒绝 ${JSON.stringify(change)}`, async () => {
    const state = fixture()
    Object.assign(state.analyses[0], change)
    await assert.rejects(verifyRelease(state.args), /CodeQL 分析 actions 缺失/)
    assert.deepEqual(state.outputs, {})
  })
}

for (const error of ['fixture processing failed', null, undefined]) {
  test(`CodeQL 分析 error 非空字符串必须拒绝 ${String(error)}`, async () => {
    const state = fixture()
    state.analyses[0].error = error
    await assert.rejects(verifyRelease(state.args), /CodeQL 分析 actions 缺失或处理失败/)
    assert.deepEqual(state.outputs, {})
  })
}

test('CodeQL 分析 API 异常必须阻止发布', async () => {
  const state = fixture()
  state.analysisError = new Error('fixture code scanning forbidden')
  await assert.rejects(verifyRelease(state.args), /code scanning forbidden/)
  assert.deepEqual(state.outputs, {})
})

test('CodeQL 最新分析失败不能使用旧成功记录', async () => {
  const state = fixture()
  state.analyses.unshift({ ...state.analyses[0], id: 200, error: 'fixture processing failed' })
  await assert.rejects(verifyRelease(state.args), /CodeQL 分析 actions 缺失或处理失败/)
  assert.deepEqual(state.outputs, {})
})

test('CodeQL 最新分析成功可以替代旧失败记录', async () => {
  const state = fixture()
  state.analyses.push({ ...state.analyses[0], id: 99, error: 'fixture processing failed' })
  await verifyRelease(state.args)
  assert.deepEqual(state.outputs, { sha: SHA })
})

test('分析 helper 使用调用者传入的 PR 合并引用与合并提交', async () => {
  const state = fixture()
  const ref = 'refs/pull/21/merge'
  const sha = 'b'.repeat(40)
  state.analyses = state.analyses.map(analysis => ({ ...analysis, ref, commit_sha: sha }))
  await requireCodeQLAnalyses({ github: state.args.github,
    owner: 'example', repo: 'project', sha, ref })
  assert.deepEqual(state.requests, [['analyses', {
    owner: 'example', repo: 'project', ref, tool_name: 'CodeQL', per_page: 100,
  }]])
})

for (const conclusion of ['skipped', 'neutral', 'missing']) {
  test(`CodeQL required 任务 ${conclusion} 必须拒绝发布`, async () => {
    const state = fixture()
    if (conclusion === 'missing') state.jobs[20].pop()
    else state.jobs[20].find(job => job.name === 'CodeQL required').conclusion = conclusion
    await assert.rejects(verifyRelease(state.args), /必需任务 CodeQL required 缺失或未成功/)
    assert.deepEqual(state.outputs, {})
  })
}

for (const id of [10, 20]) {
  for (const change of ['new run', 'rerun']) {
    test(`分析 API 查询期间工作流 ${id} 出现 ${change} 必须被末尾复核拒绝`, async () => {
      const state = fixture()
      const paginate = state.args.github.paginate
      state.args.github.paginate = async (endpoint, params) => {
        const result = await paginate(endpoint, params)
        if (endpoint === 'analyses') {
          const index = state.runs.findIndex(run => run.id === id)
          if (change === 'new run') {
            state.runs.push({ ...state.runs[index], id: id + 1,
              status: 'queued', conclusion: null })
          } else {
            state.runs[index] = { ...state.runs[index], run_attempt: 2,
              status: 'in_progress', conclusion: null }
          }
        }
        return result
      }
      await assert.rejects(verifyRelease(state.args), /检查状态已变化/)
      assert.deepEqual(state.outputs, {})
    })
  }
}
