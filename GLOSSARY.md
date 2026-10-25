# MathCraft

## Language

**正式知识库**: DeepTutor 体系中的知识库管理、文档索引、进度和 RAG provider 模块，是 MathCraft 唯一的知识库实现。

**出题编排**: `/api/generate` 与 `/api/chat` 提供的参数化和对话式出题流程；它们负责槽位、提示词、去重和结果校验，不负责独立建库或向量存储。

**知识库文档**: 正式知识库 `raw/` 目录下的文件。对外暴露的 `doc_id` 是相对于 `raw/` 的 POSIX 路径，例如 `chapter-1/limits.pdf`。

**RAG provider**: 负责解析、切分、嵌入、索引和检索的正式知识库后端。默认值为 `llamaindex`，具体知识库可以绑定其他已安装 provider。

**document_key**: 写入正式索引节点 metadata 的知识库文档相对路径，用于 `RAGService.search(..., document_keys=[...])` 的严格文档范围过滤。

**正式 LLM 配置**: 由 `/api/settings` 管理并写入运行时设置目录的模型、提供方、密钥和调用参数；出题槽位抽取与题目生成都使用这套配置。

**模型目录**: 运行时 `model_catalog.json` 中的连接、Provider Profile、模型列表和活动选择；它是模型调用的持久化来源。

**环境初始化配置**: `.env` 中用于首次生成模型目录的 `LLM_*`、`TASK_*` 和 `EMBEDDING_*` 变量；模型目录生成后，环境变量不再覆盖已保存的用户选择。

**普通知识库流程**: 以 LlamaIndex 为默认 RAG provider，使用当前文档解析引擎完成上传、解析、嵌入、索引和检索的知识库生命周期。

**旧轻量链路**: 已删除的出题服务自带 Chroma/Ollama 上传、解析、切片、嵌入和检索实现。历史运行时目录不代表当前应用仍使用该链路。
