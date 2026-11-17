const LANGUAGES = ['actions', 'javascript-typescript', 'python']

async function requireCodeQLAnalyses({ github, owner, repo, sha, ref }) {
  const analyses = await github.paginate(github.rest.codeScanning.listRecentAnalyses, {
    owner, repo, ref, tool_name: 'CodeQL', per_page: 100,
  })
  for (const language of LANGUAGES) {
    const latest = analyses.filter(analysis => analysis.ref === ref
      && analysis.commit_sha === sha && analysis.tool?.name === 'CodeQL'
      && analysis.analysis_key === '.github/workflows/codeql.yml:analyze'
      && analysis.category === `/language:${language}`)
      .sort((a, b) => b.id - a.id)[0]
    if (!latest || latest.error !== '') {
      throw new Error(`CodeQL 分析 ${language} 缺失或处理失败，禁止通过检查`)
    }
  }
}

module.exports = requireCodeQLAnalyses
