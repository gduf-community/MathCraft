# 旧 A0 / G0 独立工具

此目录是保留的历史独立工具，**不是当前 Phoenix 实现，也不属于当前应用启动和验收流程**。工具代码、独立依赖及相关测试保留，本次不修改。

旧工具包含 Agent SDK 合成 harness、正文脱敏、隔离 Phoenix 和清理验证；这些行为不适用于当前方案。不要将其配置、验收结果或真实模型烟测作为当前接入依据。

当前实现使用普通 OpenAI 客户端、私有 OpenTelemetry provider 和手工 OTLP 元数据导出，不引入 Agent SDK，不采集正文。部署使用根 `compose.phoenix.yaml`；具体说明见 [Phoenix 可选扩展](../../docs/design/Phoenix可选扩展.md)和[运行手册](../../docs/design/运维后台运行手册.md)。
