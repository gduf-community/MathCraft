# RiddleMe 后端

FastAPI + Chroma + Ollama(qwen3-embedding) + DeepSeek 的出题服务。RAG 检索教学材料，按槽位状态机引导对话出题，输出与前端 Question 结构对齐的 JSON。

## 模块结构

```
backend/
├── app/
│   ├── main.py              # FastAPI 入口 + /api/health
│   ├── config.py            # .env 配置
│   ├── schemas/question.py  # Question 模型（与前端字段对齐）
│   ├── api/
│   │   ├── kb.py            # 上传入库 / 文档清单 / 检索测试
│   │   ├── generate.py      # 参数化出题
│   │   └── chat.py          # 对话出题（槽位状态机）
│   └── services/
│       ├── parsing/         # pdf / docx / xlsx / md 解析，OCR 接口占位
│       ├── chunking.py      # 练习卷按题号切，通用按长度聚合
│       ├── embeddings.py    # qwen3-embedding:0.6b（langchain-ollama）
│       ├── vectorstore.py   # Chroma 持久化（data/chroma）
│       ├── ingestion.py     # 解析→切片→向量化→入库
│       ├── retrieval.py     # top-k 检索
│       ├── llm.py           # DeepSeek（OpenAI 兼容协议，JSON mode + 校验重试）
│       ├── question_gen.py  # 出题：检索参考 + 题型校验 + 跨题去重
│       ├── slots.py         # 对话槽位抽取/合并/追问模板
│       ├── chat_flow.py     # 对话编排
│       └── prompts.py       # 全部 prompt 模板
├── scripts/                 # 命令行测试：upload / retrieval / generate / chat
└── data/                    # chroma 库 + 上传文件（不进 git）
```

## 启动

```bash
cd backend
uv sync                                          # 首次安装依赖
uv run uvicorn app.main:app --port 8000          # 启动，Swagger 见 /docs
```

前置条件：ollama 已启动且拉取 qwen3-embedding:0.6b；.env 中配置 DeepSeek 密钥。
模型名以平台实际为准（当前支持 deepseek-flash、deepseek-v4-pro），配置在 .env 的 DEEPSEEK_MODEL。

## 测试流程

```bash
# 1. 入库（文字版 PDF / docx / xlsx / md）
uv run python scripts/upload.py "../导数与微分_50题练习卷.pdf" --kb kb-math

# 2. RAG 检索测试
uv run python scripts/test_retrieval.py "隐函数求导" --top-k 3

# 3. 参数化出题（题型:数量）
uv run python scripts/test_generate.py --types single:2,compute:1

# 4. 对话状态机联测（需先启动服务）
uv run python scripts/test_chat.py
```

## 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/health | 组件连通性自检 |
| POST | /api/kb/upload | 上传文件入库（multipart: file, kb_id） |
| GET | /api/kb/documents?kb_id= | 知识库下文档清单 |
| POST | /api/kb/search | 检索测试（kb_id, query, top_k, doc_id） |
| POST | /api/generate | 参数化出题（题型数量难度来源模式） |
| POST | /api/chat | 对话出题（槽位状态由前端每轮回传） |

## 设计要点

- **切片**：自动识别练习卷（行级题号统计 ≥5 触发），一道题一个 chunk；大题标题并入首题；「参考答案」之后整段聚合，保证原题模式可检索到答案。通用文档按 chunk_size 聚合 + overlap。
- **OCR 预留**：PDF 每页可提取字符低于阈值判定为扫描版，调用 OCREngine 协议（`parsing/base.py`），当前为占位实现，接入 PaddleOCR / MinerU 时替换 `ocr_engine` 实例即可。
- **出题质量**：JSON mode + Pydantic 校验 + 解析错误回喂重试；题型不符直接丢弃并重试（最多 3 轮）；跨题型传递已生成题干用于去重。
- **对话状态机**：槽位抽取用独立的小调用（JSON 输出），追问文案为固定模板（缺啥问啥、动态重编号），全部槽位齐备才触发生成。分数默认每题 5 分。
- **密钥安全**：DeepSeek key 只在 backend/.env（已 gitignore），前端通过 /api 代理访问，永不接触密钥。

## 待办

- 扫描版 PDF 的 OCR 引擎接入
- 题目编辑/删除/组卷记录的后端持久化（当前前端本地状态）
- 对话回复 SSE 流式输出
- 知识库管理（多知识库增删）
