const requireCodeQLAnalyses = require('./verify-codeql.cjs')

const REQUIREMENTS = [
  {
    path: '.github/workflows/checks.yml',
    name: 'Code checks',
    events: ['push', 'workflow_dispatch'],
    jobs: ['Backend lint, types and tests', 'Frontend lint, types, build and regressions'],
  },
  {
    path: '.github/workflows/codeql.yml',
    name: 'CodeQL',
    events: ['push', 'workflow_dispatch'],
    jobs: ['Analyze (actions)', 'Analyze (javascript-typescript)', 'Analyze (python)',
      'CodeQL required'],
  },
]

async function verifyRelease({ github, context, core }) {
  const { owner, repo } = context.repo
  const sha = context.sha
  const branch = context.ref.replace(/^refs\/heads\//, '')
  if (context.eventName !== 'workflow_dispatch'
      || !['refs/heads/main', 'refs/heads/agent'].includes(context.ref)
      || !/^[a-f0-9]{40}$/.test(sha)) {
    throw new Error('仅允许手动发布 main 或 agent 的固定提交')
  }

  const listRuns = () => github.paginate(github.rest.actions.listWorkflowRunsForRepo, {
    owner, repo, branch, head_sha: sha, per_page: 100,
  })
  const latestRun = (runs, required) => runs
    .filter(candidate => candidate.path === required.path
      && candidate.head_sha === sha && candidate.head_branch === branch
      && candidate.head_repository?.full_name === `${owner}/${repo}`
      && required.events.includes(candidate.event))
    .sort((a, b) => b.id - a.id)[0]
  const assertUnchanged = (required, run, current) => {
    if (!current || current.id !== run.id
        || current.head_sha !== sha || current.head_branch !== branch
        || current.head_repository?.full_name !== `${owner}/${repo}`
        || current.path !== required.path || !required.events.includes(current.event)
        || current.run_attempt !== run.run_attempt
        || current.status !== 'completed' || current.conclusion !== 'success') {
      throw new Error(`${required.name} 检查状态已变化，请等待完成后重新发布`)
    }
  }
  const runs = await listRuns()
  const selected = []
  for (const required of REQUIREMENTS) {
    const run = latestRun(runs, required)
    if (!run) {
      throw new Error(`${required.name} 缺少 ${branch}@${sha} 的检查记录；请先完成分支扫描`)
    }
    if (run.status !== 'completed' || run.conclusion !== 'success') {
      throw new Error(`${required.name} 最新运行 #${run.id} 尚未通过：`
        + `${run.status}/${run.conclusion ?? 'pending'}；请修复或等待完成后重新发布`)
    }

    const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRun, {
      owner, repo, run_id: run.id, filter: 'all', per_page: 100,
    })
    for (const name of required.jobs) {
      const candidates = jobs.filter(job => job.name === name
        && job.run_attempt <= run.run_attempt)
      const latestAttempt = Math.max(...candidates.map(job => job.run_attempt))
      const matches = candidates.filter(job => job.run_attempt === latestAttempt)
      if (matches.length !== 1 || matches[0].head_sha !== sha
          || matches[0].status !== 'completed' || matches[0].conclusion !== 'success') {
        throw new Error(`${required.name} 必需任务 ${name} 缺失或未成功，禁止发布`)
      }
    }

    const { data: current } = await github.rest.actions.getWorkflowRun({
      owner, repo, run_id: run.id,
    })
    assertUnchanged(required, run, current)
    selected.push({ required, run })
  }

  await requireCodeQLAnalyses({ github, owner, repo, sha, ref: context.ref })

  const latestRuns = await listRuns()
  for (const { required, run } of selected) {
    assertUnchanged(required, run, latestRun(latestRuns, required))
  }
  const currentRuns = await Promise.all(selected.map(({ run }) =>
    github.rest.actions.getWorkflowRun({ owner, repo, run_id: run.id })))
  const verified = []
  for (const [index, { required, run }] of selected.entries()) {
    assertUnchanged(required, run, currentRuns[index].data)
    verified.push(`${required.name}: ${run.html_url}（第 ${run.run_attempt} 次）`)
    core.info(`${required.name} 已通过：${branch}@${sha}`)
  }
  core.setOutput('sha', sha)
  await core.summary.addHeading('发布检查通过')
    .addRaw(`提交：${branch}@${sha}\n\n${verified.join('\n\n')}`).write()
}

module.exports = verifyRelease
