# 契约、文档与验收测试同步

Type: task
Status: resolved-with-environment-limit
Triage: ready-for-agent
Blocked by: 02, 03, 04, 05

同步 OpenAPI、API 文档、README、.env.example、设计文档和必要的数据库迁移说明；补充认证、初始化、管理员、资源授权和账号归属的外部行为测试。核对旧规格和旧 Issue 中冲突要求已标记为被取代。

验收：相关后端测试、前端 typecheck/lint、必要构建、OpenAPI 生成和文档检查通过；不提交真实凭据、运行时数据或旧入口说明。

规范：../spec.md


实施记录：已完成对应代码与文档同步。完整后端接口测试需要本机 Redis 15 服务可用；当前环境未启动 Redis，因此该项保留环境验证记录。
