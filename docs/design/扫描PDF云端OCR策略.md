# 扫描 PDF 的 MinerU 云端 OCR 策略

## 目标

扫描型 PDF 没有可用文字层时，知识库必须使用已配置的 MinerU 云端 OCR 生成正文、公式和版面中间结果。系统不使用本地 MinerU 模型、LiteParse 或 Docling 作为扫描 PDF 的隐式 OCR 回退。

## 使用范围

该策略作用于所有通过 `MathCraft.services.parsing.ParseService` 进入本地 RAG provider 的 PDF，包括 LlamaIndex、LightRAG 和 GraphRAG。普通文本文件、良好文字 PDF 和其他格式继续使用当前活动解析器。2026-11-04 增加页级检查、缓存优先、任务恢复与质量记录，真实云端及人工验收尚未执行。

## 配置契约

扫描 PDF 需要新外发或查询远端任务时，必须满足：

- `document_parsing.engines.mineru.mode` 为 `cloud`；
- MinerU 云端 API 地址非空；
- `api_token` 至少包含一个非空凭据；
- 本次请求在内存中强制设置 `is_ocr=true`。

MinerU 也支持启动级环境变量覆盖，变量名为 `MINERU_MODE`、`MINERU_API_BASE_URL`、`MINERU_API_TOKEN`，以及已有的其他 `MINERU_*` 解析选项。环境变量由仓库根 `.env` 加载，shell 中已有的同名变量优先，并在运行时覆盖 `document_parsing.json` 的对应字段。`is_ocr=true` 只覆盖本次扫描 PDF 请求，不回写设置文件。真实 Token 只允许放在本机 `.env` 或部署密钥系统中，不写入 `.env.example`、代码、文档或测试。

## 核心流程

```text
PDF 进入 ParseService
  ↓
检查每页正文文字、页眉页脚、图像覆盖及明显乱码
  ↓
存在正文不可用的疑似扫描页或明显损坏文字层
  ↓
解析有效身份，匹配完成缓存并重新检查质量
  ├─ 缓存兼容且检查通过 / 带警告 → 复用，不校验外发 Token
  └─ 无完成解析缓存
       ↓
      复制云端配置并强制 is_ocr=true
       ↓
      汇总兼容的完成分片；需要新外发或查询时再检查 Token
       ↓
      恢复已有 batch_id 或提交新任务 → 下载、页码与资产检查
       ↓
      质量失败阻止完成缓存和候选发布；其他结果交既有 RAG 链路
```

扫描检测在解析器选择前执行，因此不会先启动 `text_only`、本地 MinerU 或其他本地 OCR。解析缓存签名包含 `mode` 和 `is_ocr`，强制 OCR 结果不会复用普通 MinerU 解析缓存。

## 异常边界

- 没有文字层但没有页面图像的损坏或空白 PDF，不自动判定为扫描 PDF，由当前解析器报告错误。
- MinerU 不是 cloud 模式，或确需网络请求而缺少云端 Token，返回稳定错误码 `scanned_pdf_mineru_cloud_not_configured`；兼容完成缓存不因缺少 Token 被拒绝。
- 云端请求失败、超时或返回无效产物，保留具体 `cloud_*` / `parse_quality_failed` 错误；未细分的扫描解析错误仍为 `scanned_pdf_mineru_cloud_failed`。索引任务失败，不静默跳过文件。
- 全部页面正文可用、未发现疑似扫描或明显乱码的 PDF 保持当前活动解析器；含页眉文字的扫描页不能让整本绕过 OCR。原配置不回写。
- 质量检查覆盖非空内容、替换字符、明显公式占位、原页索引、坐标基本合法性及图片文件；不证明 OCR、关键公式、图示理解或数学正确性。启发式的真实误判率仍待人工验收。
- 已知远端任务重启后由显式重建继续查询；等待超预算保留任务身份。提交未知、上传接收未知或过期链接明确报告，不盲目重复上传。取消只停止本地后续工作。
- 完成解析缓存与完成分片可在无 Token 时本地复用；仍需远端查询时没有凭据应明确失败。签名和质量规则升级后的旧缓存重新检查并保留原记录。

## 验收标准

1. 当前解析器为 `text_only`、MinerU 为 `local` 且无 Token 时，上传图像型 PDF 会失败，并提示没有配置 MinerU 云端 OCR。
2. MinerU 为 `cloud`、使用假 Token、保存的 `is_ocr=false` 时，扫描 PDF 仍向 MinerU adapter 传入 `is_ocr=true`。
3. OCR 配置缺失时不调用本地 MinerU、LiteParse 或 Docling。
4. OCR 云端失败时索引任务保留 MinerU 云端失败原因，不返回空知识库成功状态。
5. 普通文本层 PDF 不触发 MinerU 云端 OCR。
6. 解析缓存对普通 MinerU 和强制 OCR 使用不同签名。

## 实现入口

- 扫描检测、缓存路由和云端配置校验：`backend/MathCraft/services/parsing/service.py`
- 通用页级、质量、原页与图像检查：`backend/MathCraft/services/parsing/quality.py`
- 统一解析错误分类：`backend/MathCraft/services/parsing/types.py`
- LlamaIndex 文档加载：`backend/MathCraft/services/rag/pipelines/llamaindex/document_loader.py`
- MinerU 云端请求与任务记录：`backend/MathCraft/services/parsing/engines/mineru/{cloud,checkpoints}.py`
- 回归测试：`backend/tests/test_scanned_pdf_ocr.py`
- 第二批自动回归：`backend/tests/test_parse_quality.py`、`backend/tests/test_mineru_recovery.py`

样本准备、恢复限制、自动检查与未验收范围见[第二批实施记录](./知识库第二批实施记录.md)。固定十页清单不被生产解析模块导入。

2026-11-04 已完成独立 home 的本地假服务及内置浏览器首轮链路验收，包含固定十页假云分片、缓存复用和重启回查；不代表真实 OCR、图示或数学质量验收。
