import type { KbDocument, KnowledgeBase, OptionItem, QuestionType, StudySpace } from '../../types'

/** 知识库列表 */
export const KNOWLEDGE_BASES: KnowledgeBase[] = [
  { id: 'kb-math', name: '高等数学知识库' },
  { id: 'kb-cs', name: '计算机基础课程知识库' },
  { id: 'kb-eng', name: '大学英语知识库' },
]

/** 各知识库下的文档 */
export const DOCUMENTS: KbDocument[] = [
  { id: 'doc-1', kbId: 'kb-math', name: '高等数学知识点汇总.pdf' },
  { id: 'doc-2', kbId: 'kb-math', name: '线性代数核心考点.pdf' },
  { id: 'doc-3', kbId: 'kb-math', name: '微积分习题精编.pdf' },
  { id: 'doc-4', kbId: 'kb-cs', name: '数据结构考点汇总.pdf' },
  { id: 'doc-5', kbId: 'kb-cs', name: '计算机网络基础.pdf' },
  { id: 'doc-6', kbId: 'kb-eng', name: '大学英语四级高频词汇.pdf' },
]

/** 可发布的学习空间 */
export const STUDY_SPACES: StudySpace[] = [
  { id: 'sp-1', name: '24软工1班' },
  { id: 'sp-2', name: '25计科2班' },
  { id: 'sp-3', name: '24大数据1班' },
  { id: 'sp-4', name: '23计科1班' },
]

interface QuestionTemplate {
  stem: string
  options: OptionItem[]
  answer: string
  analysis: string
  knowledgePoint: string
}

const choice = (label: string, text: string): OptionItem => ({ label, text })

/**
 * 题目模板库。所有内容均为演示用模拟数据，
 * 内联 LaTeX 使用 $...$ 包裹，覆盖矩阵、积分、极限等高等数学公式。
 */
export const QUESTION_BANK: Record<QuestionType, QuestionTemplate[]> = {
  single: [
    {
      stem: '下列矩阵中，行列式的值为 $-2$ 的是（　）',
      options: [
        choice('A', '$\\begin{pmatrix}1&0\\\\0&-2\\end{pmatrix}$'),
        choice('B', '$\\begin{pmatrix}2&1\\\\1&1\\end{pmatrix}$'),
        choice('C', '$\\begin{pmatrix}0&1\\\\1&0\\end{pmatrix}$'),
        choice('D', '$\\begin{pmatrix}3&1\\\\0&3\\end{pmatrix}$'),
      ],
      answer: 'A',
      analysis: '逐项计算行列式：$\\det A=1\\times(-2)-0\\times 0=-2$，其余三项分别为 $1$、$-1$、$9$，故选 A。',
      knowledgePoint: '行列式计算',
    },
    {
      stem: '函数 $f(x)=\\ln(x^2+1)$ 在 $x=0$ 处的导数为（　）',
      options: [choice('A', '$0$'), choice('B', '$1$'), choice('C', '$-1$'), choice('D', '$2$')],
      answer: 'A',
      analysis: '由求导法则 $\\dfrac{df}{dx}=\\dfrac{2x}{x^2+1}$，代入 $x=0$ 得导数值为 $0$，故选 A。',
      knowledgePoint: '导数计算',
    },
    {
      stem: '设矩阵 $A=\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}$，则 $A$ 的迹（主对角线元素之和）为（　）',
      options: [choice('A', '$3$'), choice('B', '$5$'), choice('C', '$7$'), choice('D', '$10$')],
      answer: 'B',
      analysis: '$\\operatorname{tr}(A)=a_{11}+a_{22}=1+4=5$，故选 B。',
      knowledgePoint: '矩阵的迹',
    },
    {
      stem: '极限 $\\lim\\limits_{x\\to 0}\\dfrac{\\sin x}{x}$ 的值为（　）',
      options: [choice('A', '$0$'), choice('B', '$1$'), choice('C', '$+\\infty$'), choice('D', '不存在')],
      answer: 'B',
      analysis: '这是重要极限之一，$\\lim\\limits_{x\\to 0}\\dfrac{\\sin x}{x}=1$，故选 B。',
      knowledgePoint: '重要极限',
    },
    {
      stem: '下列反常积分中收敛的是（　）',
      options: [
        choice('A', '$\\int_1^{+\\infty}\\dfrac{1}{x}\\,dx$'),
        choice('B', '$\\int_1^{+\\infty}\\dfrac{1}{x^2}\\,dx$'),
        choice('C', '$\\int_0^1\\dfrac{1}{x}\\,dx$'),
        choice('D', '$\\int_1^{+\\infty}\\ln x\\,dx$'),
      ],
      answer: 'B',
      analysis: '$\\int_1^{+\\infty}\\dfrac{1}{x^2}\\,dx=\\left[-\\dfrac{1}{x}\\right]_1^{+\\infty}=1$ 收敛；A、C、D 均发散，故选 B。',
      knowledgePoint: '反常积分',
    },
    {
      stem: '设 $z=x^2y$，则 $\\dfrac{\\partial z}{\\partial x}$ 等于（　）',
      options: [choice('A', '$2xy$'), choice('B', '$x^2$'), choice('C', '$x^2y$'), choice('D', '$2x$')],
      answer: 'A',
      analysis: '对 $x$ 求偏导时把 $y$ 看作常数，得 $\\dfrac{\\partial z}{\\partial x}=2xy$，故选 A。',
      knowledgePoint: '偏导数',
    },
  ],

  multiple: [
    {
      stem: '设 $E=\\begin{pmatrix}1&0\\\\0&1\\end{pmatrix}$ 为二阶单位矩阵，下列说法正确的有（　）',
      options: [
        choice('A', '$\\det E=1$'),
        choice('B', '$E$ 的逆矩阵是它自身'),
        choice('C', '$E$ 的特征值均为 $1$'),
        choice('D', '$E$ 的迹为 $0$'),
      ],
      answer: 'ABC',
      analysis: '$\\det E=1$，$E^{-1}=E$，特征值为 $1,1$；而 $\\operatorname{tr}(E)=2\\neq 0$，D 错误，故选 ABC。',
      knowledgePoint: '单位矩阵',
    },
    {
      stem: '下列极限中存在且等于 $0$ 的有（　）',
      options: [
        choice('A', '$\\lim\\limits_{x\\to\\infty}\\dfrac{1}{x}$'),
        choice('B', '$\\lim\\limits_{x\\to 0}x\\sin\\dfrac{1}{x}$'),
        choice('C', '$\\lim\\limits_{n\\to\\infty}\\dfrac{n}{n+1}$'),
        choice('D', '$\\lim\\limits_{x\\to 0}\\left(e^x-1\\right)$'),
      ],
      answer: 'ABD',
      analysis: 'A、B、D 的极限均为 $0$；C 的极限为 $1$，故选 ABD。',
      knowledgePoint: '极限运算',
    },
    {
      stem: '设向量 $\\vec{a}=(1,2)$，$\\vec{b}=(-2,1)$，则（　）',
      options: [
        choice('A', '$\\vec{a}\\perp\\vec{b}$'),
        choice('B', '$|\\vec{a}|=\\sqrt{5}$'),
        choice('C', '$\\vec{a}\\cdot\\vec{b}=0$'),
        choice('D', '$\\vec{a}\\parallel\\vec{b}$'),
      ],
      answer: 'ABC',
      analysis: '$\\vec{a}\\cdot\\vec{b}=1\\times(-2)+2\\times 1=0$，故垂直；$|\\vec{a}|=\\sqrt{1^2+2^2}=\\sqrt{5}$，故选 ABC。',
      knowledgePoint: '向量的数量积',
    },
    {
      stem: '下列级数中收敛的有（　）',
      options: [
        choice('A', '$\\sum\\limits_{n=1}^{\\infty}\\dfrac{1}{n^2}$'),
        choice('B', '$\\sum\\limits_{n=1}^{\\infty}\\dfrac{1}{n}$'),
        choice('C', '$\\sum\\limits_{n=1}^{\\infty}\\dfrac{1}{2^n}$'),
        choice('D', '$\\sum\\limits_{n=1}^{\\infty}\\dfrac{1}{\\sqrt{n}}$'),
      ],
      answer: 'AC',
      analysis: 'A 为 $p=2>1$ 的 $p$ 级数，收敛；C 为公比 $q=\\tfrac{1}{2}$ 的等比级数，收敛；B、D 均发散，故选 AC。',
      knowledgePoint: '级数敛散性',
    },
    {
      stem: '关于二次型 $f(x_1,x_2)=x_1^2+2x_2^2$，下列说法正确的有（　）',
      options: [
        choice('A', '$f$ 是正定二次型'),
        choice('B', '$f$ 的秩为 $2$'),
        choice('C', '$f$ 的矩阵为 $\\begin{pmatrix}1&0\\\\0&2\\end{pmatrix}$'),
        choice('D', '$f$ 可以取到负值'),
      ],
      answer: 'ABC',
      analysis: '正惯性指数为 $2$，故 $f$ 正定且秩为 $2$；其矩阵即平方项系数构成的对角阵；正定意味着 $f\\ge 0$ 恒成立，D 错误。故选 ABC。',
      knowledgePoint: '二次型',
    },
  ],

  judge: [
    {
      stem: '可逆矩阵的行列式一定不为 $0$。',
      options: [choice('A', '正确'), choice('B', '错误')],
      answer: 'A',
      analysis: '若 $\\det A=0$，则 $A$ 不可逆；反之可逆矩阵的行列式必非零，故正确。',
      knowledgePoint: '可逆矩阵',
    },
    {
      stem: '函数在某点可导，则它在该点必定连续。',
      options: [choice('A', '正确'), choice('B', '错误')],
      answer: 'A',
      analysis: '可导必连续，这是连续与可导关系的基本结论；反之连续不一定可导，如 $y=|x|$ 在 $x=0$ 处。',
      knowledgePoint: '连续与可导',
    },
    {
      stem: '若 $\\lim\\limits_{n\\to\\infty}a_n=0$，则级数 $\\sum\\limits_{n=1}^{\\infty}a_n$ 必收敛。',
      options: [choice('A', '正确'), choice('B', '错误')],
      answer: 'B',
      analysis: '通项趋于零只是收敛的必要条件。反例：调和级数 $\\sum\\limits_{n=1}^{\\infty}\\dfrac{1}{n}$ 通项趋于零但发散。',
      knowledgePoint: '级数收敛条件',
    },
    {
      stem: '实对称矩阵的特征值必为实数。',
      options: [choice('A', '正确'), choice('B', '错误')],
      answer: 'A',
      analysis: '实对称矩阵的特征值均为实数，且不同特征值对应的特征向量正交，这是实对称矩阵的基本性质。',
      knowledgePoint: '实对称矩阵',
    },
    {
      stem: '两个无穷小量的商的极限一定是 $1$。',
      options: [choice('A', '正确'), choice('B', '错误')],
      answer: 'B',
      analysis: '商的极限可能出现多种情况：$\\lim\\limits_{x\\to 0}\\dfrac{\\sin x}{x}=1$，而 $\\lim\\limits_{x\\to 0}\\dfrac{x^2}{x}=0$，故错误。',
      knowledgePoint: '无穷小量',
    },
  ],

  blank: [
    {
      stem: '设 $A=\\begin{pmatrix}1&2\\\\0&1\\end{pmatrix}$，则 $A^{-1}=$ \\underline{\\hspace{3em}}。',
      options: [],
      answer: '$\\begin{pmatrix}1&-2\\\\0&1\\end{pmatrix}$',
      analysis: '二阶上三角矩阵求逆口诀：主对角线取倒数，右上角元素变号，即得 $A^{-1}=\\begin{pmatrix}1&-2\\\\0&1\\end{pmatrix}$。',
      knowledgePoint: '逆矩阵',
    },
    {
      stem: '曲线 $y=x^3$ 在点 $(1,1)$ 处的切线斜率为 \\underline{\\hspace{3em}}。',
      options: [],
      answer: '$3$',
      analysis: '由 $\\dfrac{dy}{dx}=3x^2$，代入 $x=1$ 得切线斜率为 $3$。',
      knowledgePoint: '导数的几何意义',
    },
    {
      stem: '$\\int_0^1 x^2\\,dx=$ \\underline{\\hspace{3em}}。',
      options: [],
      answer: '$\\dfrac{1}{3}$',
      analysis: '$\\int_0^1 x^2\\,dx=\\left[\\dfrac{x^3}{3}\\right]_0^1=\\dfrac{1}{3}$。',
      knowledgePoint: '定积分计算',
    },
    {
      stem: '设 $\\vec{a}=(1,0,1)$，$\\vec{b}=(0,1,1)$，则 $\\vec{a}\\times\\vec{b}=$ \\underline{\\hspace{3em}}。',
      options: [],
      answer: '$(-1,-1,1)$',
      analysis: '按行列式法则展开：$\\vec{a}\\times\\vec{b}=\\begin{vmatrix}\\vec{i}&\\vec{j}&\\vec{k}\\\\1&0&1\\\\0&1&1\\end{vmatrix}=(-1,-1,1)$。',
      knowledgePoint: '向量的叉积',
    },
    {
      stem: '矩阵 $\\begin{pmatrix}2&0\\\\0&3\\end{pmatrix}$ 的特征值为 \\underline{\\hspace{3em}}。',
      options: [],
      answer: '$2$ 和 $3$',
      analysis: '对角矩阵的特征值就是主对角线上的元素，即 $2$ 与 $3$。',
      knowledgePoint: '特征值',
    },
  ],

  compute: [
    {
      stem: '已知矩阵 $A=\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}$，求 $A$ 的行列式、逆矩阵以及全部特征值。',
      options: [],
      answer: '$\\det A=-2$；$A^{-1}=\\begin{pmatrix}-2&1\\\\\\tfrac{3}{2}&-\\tfrac{1}{2}\\end{pmatrix}$；特征值 $\\lambda_{1,2}=\\dfrac{5\\pm\\sqrt{33}}{2}$。',
      analysis: '$\\det A=1\\times 4-2\\times 3=-2$；伴随矩阵 $A^{*}=\\begin{pmatrix}4&-2\\\\-3&1\\end{pmatrix}$，故 $A^{-1}=\\dfrac{1}{\\det A}A^{*}$；特征方程 $\\lambda^2-5\\lambda-2=0$，解得 $\\lambda_{1,2}=\\dfrac{5\\pm\\sqrt{33}}{2}$。',
      knowledgePoint: '矩阵运算',
    },
    {
      stem: '计算极限 $\\lim\\limits_{x\\to 0}\\dfrac{e^x-1-x}{x^2}$。',
      options: [],
      answer: '$\\dfrac{1}{2}$',
      analysis: '用泰勒展开 $e^x=1+x+\\dfrac{x^2}{2}+o(x^2)$，代入得 $\\lim\\limits_{x\\to 0}\\dfrac{\\tfrac{x^2}{2}+o(x^2)}{x^2}=\\dfrac{1}{2}$；连续使用两次洛必达法则结果相同。',
      knowledgePoint: '泰勒展开',
    },
    {
      stem: '求二重积分 $\\iint\\limits_{D}(x+y)\\,dx\\,dy$，其中 $D$ 由直线 $x=0$、$y=0$ 与 $x+y=1$ 围成。',
      options: [],
      answer: '$\\dfrac{1}{3}$',
      analysis: '化为累次积分 $\\int_0^1\\!\\!\\int_0^{1-x}(x+y)\\,dy\\,dx$，先算内层得 $x(1-x)+\\dfrac{(1-x)^2}{2}$，再积分得 $\\dfrac{1}{3}$。',
      knowledgePoint: '二重积分',
    },
    {
      stem: '设 $A=\\begin{pmatrix}0&1\\\\1&0\\end{pmatrix}$，求 $A^{2026}$。',
      options: [],
      answer: '$A^{2026}=E=\\begin{pmatrix}1&0\\\\0&1\\end{pmatrix}$',
      analysis: '计算得 $A^2=\\begin{pmatrix}1&0\\\\0&1\\end{pmatrix}=E$，而 $2026=2\\times 1013$，故 $A^{2026}=(A^2)^{1013}=E$。',
      knowledgePoint: '矩阵幂运算',
    },
    {
      stem: '求二阶常系数齐次线性微分方程 $\\dfrac{d^2y}{dx^2}+y=0$ 的通解。',
      options: [],
      answer: '$y=C_1\\cos x+C_2\\sin x$（$C_1,C_2$ 为任意常数）',
      analysis: '特征方程 $r^2+1=0$，特征根为一对共轭复根 $r=\\pm i$，故通解为 $y=C_1\\cos x+C_2\\sin x$。',
      knowledgePoint: '二阶微分方程',
    },
  ],

  essay: [
    {
      stem: '简述矩阵 $A$ 可逆的充分必要条件，并举一个二阶矩阵的例子说明。',
      options: [],
      answer: '$A$ 可逆的充分必要条件是 $\\det A\\neq 0$（即 $A$ 满秩）。例如 $A=\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}$，$\\det A=-2\\neq 0$，故 $A$ 可逆。',
      analysis: '要点：行列式非零、秩等于阶数、特征值均非零三者等价，任取其一作为判据即可。',
      knowledgePoint: '可逆矩阵',
    },
    {
      stem: '简述洛必达法则的使用条件，并说明使用时需要注意什么。',
      options: [],
      answer: '使用条件：① 极限为 $\\tfrac{0}{0}$ 或 $\\tfrac{\\infty}{\\infty}$ 型未定式；② 分子分母在去心邻域内可导且分母不为零；③ 导数比的极限存在或为无穷大。注意：不满足条件时不能使用，且应先化简再求导。',
      analysis: '要点：先验证未定式类型；求导后极限不存在时法则失效；能化简的先化简，避免越导越复杂。',
      knowledgePoint: '洛必达法则',
    },
    {
      stem: '简述非齐次线性方程组 $A\\vec{x}=\\vec{b}$ 有唯一解的充分必要条件。',
      options: [],
      answer: '系数矩阵与增广矩阵的秩相等且等于未知数个数，即 $r(A)=r(A,\\vec{b})=n$。',
      analysis: '要点：若 $r(A)\\neq r(A,\\vec{b})$ 则无解；若 $r(A)=r(A,\\vec{b})<n$ 则有无穷多解；两者相等且等于 $n$ 时有唯一解。',
      knowledgePoint: '线性方程组',
    },
    {
      stem: '简述函数 $f(x)$ 在 $x_0$ 处取得极值的必要条件与两个充分条件。',
      options: [],
      answer: '必要条件：可导时 $\\left.\\dfrac{df}{dx}\\right|_{x=x_0}=0$，即驻点。第一充分条件：$x_0$ 两侧一阶导数变号，左正右负为极大值，左负右正为极小值。第二充分条件：二阶导数 $\\left.\\dfrac{d^2f}{dx^2}\\right|_{x=x_0}<0$ 时取极大值，$>0$ 时取极小值。',
      analysis: '要点：驻点与不可导点都是嫌疑点；两个充分条件分别从一阶与二阶导数的角度给出判定。',
      knowledgePoint: '函数极值',
    },
    {
      stem: '简述向量组线性相关的定义，并给出两种常用的判定方法。',
      options: [],
      answer: '定义：存在不全为零的数 $k_1,\\dots,k_s$，使 $k_1\\vec{\\alpha}_1+\\cdots+k_s\\vec{\\alpha}_s=\\vec{0}$，则称向量组线性相关。判定方法：① 向量组的秩小于向量个数；② 以向量为列作齐次方程组，有非零解即相关。',
      analysis: '要点：定义法、秩判别法；对方阵还可看行列式是否为零。',
      knowledgePoint: '线性相关性',
    },
  ],
}
