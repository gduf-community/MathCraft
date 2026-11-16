# 旧登录冒烟脚本归档

`smoke_live.py` 和 `smoke_paper_live.py` 保留原始内容，仅供历史排查，不属于当前测试或启动入口。

两者依赖已移除的 `/api/auth/login` 和旧 `token` 响应字段，无法用于当前登录契约。脚本还会连接服务或创建业务数据，不能在当前开发库、已有账号或生产环境执行。当前接口与隔离数据回归位于 `backend/tests/`；完整业务串联由 `test_full_flow.py` 覆盖，使用假模型和临时数据库。
