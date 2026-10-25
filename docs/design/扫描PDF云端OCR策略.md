# 扫描 PDF 的 MinerU 云端 OCR 策略

## 目标

扫描型 PDF 没有可用文字层时，知识库必须使用已配置的 MinerU 云端 OCR 生成正文、公式和版面中间结果。系统不使用本地 MinerU 模型、LiteParse 或 Docling 作为扫描 PDF 的隐式 OCR 回退。

## 使用范围

该策略作用于所有通过 `math_q_agent.services.parsing.ParseService` 进入本地 RAG provider 的 PDF，包括 LlamaIndex、LightRAG 和 GraphRAG。普通文本文件、非扫描 PDF 和其他格式继续使用当前活动解析器。

## 配置契约

扫描 PDF 触发 OCR 前，必须满足：

- `document_parsing.engines.mineru.mode` 为 `cloud`；
- MinerU 云端 API 地址非空；
- `api_token` 至少包含一个非空凭据；
- 本次请求在内存中强制设置 `is_ocr=true`。

MinerU 也支持启动级环境变量覆盖，变量名为 `MINERU_MODE`、`MINERU_API_BASE_URL`、`MINERU_API_TOKEN`，以及已有的其他 `MINERU_*` 解析选项。环境变量由仓库根 `.env` 加载，shell 中已有的同名变量优先，并在运行时覆盖 `document_parsing.json` 的对应字段。`is_ocr=true` 只覆盖本次扫描 PDF 请求，不回写设置文件。真实 Token 只允许放在本机 `.env` 或部署密钥系统中，不写入 `.env.example`、代码、文档或测试。

## 核心流程

```text
PDF 进入 ParseService
  ↓
检查每页文字层和嵌入页面图像
  ↓
存在页面图像且全部没有可提取文字
  ↓
读取 MinerU 配置
  ├─ 不是 cloud / 地址为空 / Token 为空
  │    └─ 失败：扫描型 PDF 无法启动 MinerU 云端 OCR
  └─ 配置完整
       ↓
      复制配置并强制 is_ocr=true
       ↓
      通过现有 MinerU cloud adapter、缓存、签名和统一 IR 解析
       ↓
      交给绑定的 RAG provider 建立索引
```

扫描检测在解析器选择前执行，因此不会先启动 `text_only`、本地 MinerU 或其他本地 OCR。解析缓存签名包含 `mode` 和 `is_ocr`，强制 OCR 结果不会复用普通 MinerU 解析缓存。

## 异常边界

- 没有文字层但没有页面图像的损坏或空白 PDF，不自动判定为扫描 PDF，由当前解析器报告错误。
- MinerU 不是 cloud 模式，或缺少云端 Token，返回稳定错误码 `scanned_pdf_mineru_cloud_not_configured`。
- 云端请求失败、超时或返回无效产物，返回稳定错误码 `scanned_pdf_mineru_cloud_failed`，索引任务失败，不静默跳过文件。
- 已经有可提取文字的 PDF 不触发扫描 OCR，不改变当前活动解析器和普通 MinerU 的 `is_ocr` 配置。
- 当前策略只识别“文字层完全为空”的扫描 PDF；低质量乱码、少量页眉页脚或公式缺失属于后续质量门禁范围。

## 验收标准

1. 当前解析器为 `text_only`、MinerU 为 `local` 且无 Token 时，上传图像型 PDF 会失败，并提示没有配置 MinerU 云端 OCR。
2. MinerU 为 `cloud`、使用假 Token、保存的 `is_ocr=false` 时，扫描 PDF 仍向 MinerU adapter 传入 `is_ocr=true`。
3. OCR 配置缺失时不调用本地 MinerU、LiteParse 或 Docling。
4. OCR 云端失败时索引任务保留 MinerU 云端失败原因，不返回空知识库成功状态。
5. 普通文本层 PDF 不触发 MinerU 云端 OCR。
6. 解析缓存对普通 MinerU 和强制 OCR 使用不同签名。

## 实现入口

- 扫描检测和云端配置校验：`backend/math_q_agent/services/parsing/service.py`
- 统一解析错误分类：`backend/math_q_agent/services/parsing/types.py`
- LlamaIndex 文档加载：`backend/math_q_agent/services/rag/pipelines/llamaindex/document_loader.py`
- MinerU 云端请求：`backend/math_q_agent/services/parsing/engines/mineru/cloud.py`
- 回归测试：`backend/tests/test_scanned_pdf_ocr.py`
