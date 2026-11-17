const SEMVER = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?![\s\S])/
const SHA = /^[a-f0-9]{40}(?![\s\S])/

function isValidReleaseTag(tag) {
  return typeof tag === 'string' && SEMVER.test(tag)
}

async function validateReleaseTag({ github, context, core }) {
  let tag
  if (context.eventName === 'push' && context.payload?.deleted !== true
      && typeof context.ref === 'string' && context.ref.startsWith('refs/tags/')) {
    tag = context.ref.slice('refs/tags/'.length)
  } else if (context.eventName === 'release' && context.payload?.action === 'published'
      && context.payload.release?.draft === false) {
    tag = context.payload.release.tag_name
    if (context.ref !== `refs/tags/${tag}`) throw new Error('Release 的 tag 与事件 ref 不一致')
  } else {
    throw new Error('仅接受 tag push 或 release.published 事件，禁止删除 tag')
  }
  if (!isValidReleaseTag(tag)) {
    throw new Error('发布 tag 必须为裸 SemVer 2.0.0，禁止 v 前缀或数字前导零')
  }
  if (typeof context.sha !== 'string' || !SHA.test(context.sha)) {
    throw new Error('发布事件缺少有效固定 SHA')
  }

  const { data: reference } = await github.rest.git.getRef({
    ...context.repo, ref: `tags/${tag}`,
  })
  if (reference.ref !== `refs/tags/${tag}`) throw new Error('Git API 返回的 tag ref 不匹配')
  let object = reference.object
  const eventObjectSha = object?.sha
  const seen = new Set()
  while (object?.type === 'tag') {
    if (!SHA.test(object.sha) || seen.has(object.sha) || seen.size >= 10) {
      throw new Error('附注 tag 对象无效、循环或嵌套过深')
    }
    seen.add(object.sha)
    const { data } = await github.rest.git.getTag({ ...context.repo, tag_sha: object.sha })
    object = data.object
  }
  if (object?.type !== 'commit' || typeof object.sha !== 'string' || !SHA.test(object.sha)) {
    throw new Error('发布 tag 必须指向有效 Git commit')
  }
  if (context.sha !== object.sha && context.sha !== eventObjectSha) {
    throw new Error('Tag 目标已偏离触发事件 SHA，禁止发布')
  }
  const result = { version: tag, sha: object.sha }
  core.setOutput('version', result.version)
  core.setOutput('sha', result.sha)
  core.info(`发布 tag 已固定：${tag}@${result.sha}`)
  return result
}

async function requireLongTermBranchChecks({ github, context, core, sha,
  verify = require('./verify-release.cjs') }) {
  if (typeof sha !== 'string' || !SHA.test(sha)) throw new Error('发布 SHA 无效')
  const failures = []
  for (const branch of ['main', 'agent']) {
    try {
      await verify({ github, core,
        context: { ...context, repo: context.repo, sha,
          ref: `refs/heads/${branch}`, eventName: 'workflow_dispatch' } })
      core.info(`发布提交已通过长期分支门禁：${branch}@${sha}`)
      return branch
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error)
      const message = `${branch}@${sha} 发布候选校验失败：${reason}`
      failures.push(message)
      core.warning(message)
    }
  }
  throw new Error(`所有长期分支候选均未通过，禁止发布：\n${failures.join('\n')}`)
}

module.exports = validateReleaseTag
module.exports.isValidReleaseTag = isValidReleaseTag
module.exports.requireLongTermBranchChecks = requireLongTermBranchChecks
