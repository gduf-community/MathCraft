const assert = require('node:assert/strict')
const { test } = require('node:test')
const validateReleaseTag = require('./validate-release-tag.cjs')
const { isValidReleaseTag, requireLongTermBranchChecks } = validateReleaseTag

const COMMIT = 'a'.repeat(40)
const TAG_OBJECT = 'b'.repeat(40)

for (const version of [
  '0.0.0', '1.2.3', '10.20.30', '1.2.3-0', '1.2.3-alpha.1',
  '1.2.3-01alpha', '1.2.3-001a', '1.2.3--', '1.2.3-alpha-01',
  '1.2.3+001', '1.2.3+build.01', '1.2.3-rc.0+build.001',
  '999999999999999999999.2.3',
]) {
  test(`接受裸 SemVer ${version}`, () => assert.equal(isValidReleaseTag(version), true))
}

for (const version of [
  '', 'v1.2.3', 'V1.2.3', '1.2', '1.2.3.4', '01.2.3', '1.02.3', '1.2.03',
  '1.2.3-01', '1.2.3-00', '1.2.3-alpha.01', '1.2.3-01.alpha',
  '1.2.3-', '1.2.3+', '1.2.3-a..b', '1.2.3+a..b', '1.2.3-a_b',
  '1.2.3+build_1', '1.2.3+abc+def', '1.2.3/other',
  ' 1.2.3', '1.2.3 ', '1.2.3\n', '1.2.3\r\n', '1.2.3\u2028',
  '1.2.3\u2029', '1.2.3\0', 'prefix1.2.3', '1.2.3$(id)',
  '１.2.3', '1.2.3-α', null, undefined, 123, {},
]) {
  test(`拒绝非严格 SemVer ${JSON.stringify(version)}`, () =>
    assert.equal(isValidReleaseTag(version), false))
}

function fixture() {
  const state = { outputs: {}, requests: [], messages: [], warnings: [],
    reference: { ref: 'refs/tags/1.2.3', object: { type: 'commit', sha: COMMIT } },
    tags: {} }
  state.args = {
    context: { repo: { owner: 'example', repo: 'project' }, eventName: 'push',
      ref: 'refs/tags/1.2.3', sha: COMMIT, payload: { deleted: false } },
    core: {
      setOutput(name, value) { state.outputs[name] = value },
      info(message) { state.messages.push(message) },
      warning(message) { state.warnings.push(message) },
    },
    github: { rest: { git: {
      async getRef(params) {
        state.requests.push(['getRef', params])
        if (state.error) throw state.error
        return { data: structuredClone(state.reference) }
      },
      async getTag(params) {
        state.requests.push(['getTag', params])
        if (state.tagError) throw state.tagError
        return { data: { object: structuredClone(state.tags[params.tag_sha]) } }
      },
    } } },
  }
  return state
}

test('轻量 tag 解析固定 commit 并输出版本和 SHA', async () => {
  const state = fixture()
  const result = await validateReleaseTag(state.args)
  assert.deepEqual(result, { version: '1.2.3', sha: COMMIT })
  assert.deepEqual(state.outputs, result)
  assert.deepEqual(state.requests, [['getRef', {
    owner: 'example', repo: 'project', ref: 'tags/1.2.3',
  }]])
})

for (const eventSha of [COMMIT, TAG_OBJECT]) {
  test(`附注 tag 固定底层 commit，支持事件 SHA ${eventSha}`, async () => {
    const state = fixture()
    state.args.context.sha = eventSha
    state.reference.object = { type: 'tag', sha: TAG_OBJECT }
    state.tags[TAG_OBJECT] = { type: 'commit', sha: COMMIT }
    await validateReleaseTag(state.args)
    assert.deepEqual(state.outputs, { version: '1.2.3', sha: COMMIT })
    assert.deepEqual(state.requests[1], ['getTag', {
      owner: 'example', repo: 'project', tag_sha: TAG_OBJECT,
    }])
  })
}

test('release.published 从 release.tag_name 校验并固定提交', async () => {
  const state = fixture()
  state.args.context.eventName = 'release'
  state.args.context.payload = { action: 'published',
    release: { tag_name: '1.2.3', draft: false, prerelease: false } }
  await validateReleaseTag(state.args)
  assert.deepEqual(state.outputs, { version: '1.2.3', sha: COMMIT })
})

test('预发布版本与 build metadata 保持原样', async () => {
  const state = fixture()
  const version = '1.2.3-rc.0+build.001'
  state.args.context.eventName = 'release'
  state.args.context.ref = `refs/tags/${version}`
  state.args.context.payload = { action: 'published',
    release: { tag_name: version, draft: false, prerelease: true } }
  state.reference.ref = state.args.context.ref
  await validateReleaseTag(state.args)
  assert.deepEqual(state.outputs, { version, sha: COMMIT })
})

for (const context of [
  { eventName: 'workflow_dispatch' }, { eventName: 'pull_request' },
  { ref: 'refs/heads/main' }, { payload: { deleted: true } },
  { ref: 'refs/tags/v1.2.3' }, { ref: 'refs/tags/1.2.3\n' },
  { sha: 'main' }, { sha: COMMIT + '\n' },
  { eventName: 'release', payload: { action: 'created',
    release: { tag_name: '1.2.3', draft: false } } },
  { eventName: 'release', payload: { action: 'published',
    release: { tag_name: '1.2.3', draft: true } } },
  { eventName: 'release', payload: { action: 'published',
    release: { tag_name: '2.0.0', draft: false } } },
]) {
  test(`无效发布事件必须在 API 查询前拒绝 ${JSON.stringify(context)}`, async () => {
    const state = fixture()
    Object.assign(state.args.context, context)
    await assert.rejects(validateReleaseTag(state.args))
    assert.deepEqual(state.outputs, {})
    assert.deepEqual(state.requests, [])
  })
}

for (const object of [
  { type: 'tree', sha: COMMIT }, { type: 'blob', sha: COMMIT },
  { type: 'commit', sha: 'invalid' }, { type: 'commit', sha: COMMIT + '\n' },
  { type: 'commit', sha: 'c'.repeat(40) }, null,
]) {
  test(`tag 无有效且一致的 commit 时拒绝 ${JSON.stringify(object)}`, async () => {
    const state = fixture()
    state.reference.object = object
    await assert.rejects(validateReleaseTag(state.args))
    assert.deepEqual(state.outputs, {})
  })
}

test('拒绝 API 返回其他 tag', async () => {
  const state = fixture()
  state.reference.ref = 'refs/tags/2.0.0'
  await assert.rejects(validateReleaseTag(state.args), /ref 不匹配/)
  assert.deepEqual(state.outputs, {})
})

test('嵌套附注 tag 解析到同一固定提交', async () => {
  const state = fixture()
  state.reference.object = { type: 'tag', sha: TAG_OBJECT }
  state.tags[TAG_OBJECT] = { type: 'tag', sha: 'c'.repeat(40) }
  state.tags['c'.repeat(40)] = { type: 'commit', sha: COMMIT }
  await validateReleaseTag(state.args)
  assert.equal(state.outputs.sha, COMMIT)
})

test('附注 tag 循环必须拒绝', async () => {
  const state = fixture()
  state.reference.object = { type: 'tag', sha: TAG_OBJECT }
  state.tags[TAG_OBJECT] = { type: 'tag', sha: TAG_OBJECT }
  await assert.rejects(validateReleaseTag(state.args), /循环或嵌套过深/)
  assert.deepEqual(state.outputs, {})
})

test('附注 tag 超过十层必须拒绝', async () => {
  const state = fixture()
  const shas = Array.from({ length: 11 }, (_, index) => (index + 1).toString(16).padStart(40, '0'))
  state.reference.object = { type: 'tag', sha: shas[0] }
  for (const [index, sha] of shas.entries()) {
    state.tags[sha] = index === shas.length - 1
      ? { type: 'commit', sha: COMMIT } : { type: 'tag', sha: shas[index + 1] }
  }
  await assert.rejects(validateReleaseTag(state.args), /循环或嵌套过深/)
  assert.deepEqual(state.outputs, {})
})

for (const operation of ['getRef', 'getTag']) {
  test(`${operation} API 异常必须拒绝发布`, async () => {
    const state = fixture()
    if (operation === 'getRef') state.error = new Error('fixture ref forbidden')
    else {
      state.reference.object = { type: 'tag', sha: TAG_OBJECT }
      state.tagError = new Error('fixture tag forbidden')
    }
    await assert.rejects(validateReleaseTag(state.args), /fixture .* forbidden/)
    assert.deepEqual(state.outputs, {})
  })
}

test('main 通过时使用固定 SHA 合成门禁上下文，不修改原 context', async () => {
  const state = fixture()
  const original = structuredClone(state.args.context)
  const calls = []
  const branch = await requireLongTermBranchChecks({ ...state.args, sha: COMMIT,
    verify: async args => { calls.push(args) } })
  assert.equal(branch, 'main')
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].context, { ...original, sha: COMMIT,
    ref: 'refs/heads/main', eventName: 'workflow_dispatch' })
  assert.deepEqual(state.args.context, original)
  assert.equal(calls[0].github, state.args.github)
  assert.equal(calls[0].core, state.args.core)
  assert.deepEqual(state.warnings, [])
})

test('门禁保留 Actions Context 原型 getter 提供的仓库身份', async () => {
  const state = fixture()
  const repository = state.args.context.repo
  const prototype = { get repo() { return repository } }
  const actionContext = Object.create(prototype)
  for (const [name, value] of Object.entries(state.args.context)) {
    if (name !== 'repo') actionContext[name] = value
  }
  assert.equal(Object.hasOwn(actionContext, 'repo'), false)
  const branch = await requireLongTermBranchChecks({ ...state.args, context: actionContext,
    sha: COMMIT, verify: async ({ context }) => {
      const { owner, repo } = context.repo
      assert.deepEqual({ owner, repo }, repository)
      assert.equal(context.sha, COMMIT)
    } })
  assert.equal(branch, 'main')
  assert.equal(actionContext.repo, repository)
})

test('main 候选失败必须报告原因，并允许同 SHA 的 agent 成功', async () => {
  const state = fixture()
  const calls = []
  const branch = await requireLongTermBranchChecks({ ...state.args, sha: COMMIT,
    verify: async ({ context }) => {
      calls.push(context)
      if (context.ref === 'refs/heads/main') throw new Error('fixture main CI failed')
    } })
  assert.equal(branch, 'agent')
  assert.deepEqual(calls.map(context => [context.ref, context.sha, context.eventName]), [
    ['refs/heads/main', COMMIT, 'workflow_dispatch'],
    ['refs/heads/agent', COMMIT, 'workflow_dispatch'],
  ])
  assert.equal(state.warnings.length, 1)
  assert.match(state.warnings[0], /main@.*fixture main CI failed/)
})

test('两个长期分支失败必须报告各自原因并拒绝', async () => {
  const state = fixture()
  await assert.rejects(requireLongTermBranchChecks({ ...state.args, sha: COMMIT,
    verify: async ({ context }) => { throw new Error(`fixture ${context.ref} failed`) } }),
  error => /main@.*fixture refs\/heads\/main failed/.test(error.message)
    && /agent@.*fixture refs\/heads\/agent failed/.test(error.message))
  assert.equal(state.warnings.length, 2)
})

test('非 Error 的候选失败也必须报告并拒绝', async () => {
  const state = fixture()
  await assert.rejects(requireLongTermBranchChecks({ ...state.args, sha: COMMIT,
    verify: async () => { throw 'fixture failure' } }), /fixture failure/)
  assert.equal(state.warnings.length, 2)
})

test('无效 SHA 不调用长期分支门禁', async () => {
  const state = fixture()
  let called = false
  await assert.rejects(requireLongTermBranchChecks({ ...state.args, sha: 'main',
    verify: async () => { called = true } }), /SHA 无效/)
  assert.equal(called, false)
})
