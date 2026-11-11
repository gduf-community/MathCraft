# MathCraft API

本文件由根目录 `openapi.json` 自动生成；运行时契约以 `/openapi.json` 和 `/docs` 为准。

后端入口为 `app.main:app`，示例地址 `http://127.0.0.1:8000`。除健康检查及公开认证流程外，受保护 HTTP 接口使用 `Authorization: Bearer <access_token>`；刷新要求 HttpOnly Cookie、可信 Origin 和 `X-CSRF-Token`；退出另外要求本标签的 `Authorization`，仅撤销该访问令牌绑定的会话，不清除其他会话的共享 Cookie。

认证、资料字段、错误响应以 OpenAPI schema 为准，不再使用历史单用户设置接口。完整认证与迁移约定见 [用户系统实施规格](design/用户系统实施规格.md) 和[认证设计](design/用户系统功能规格.md)。

模型凭据使用 `/api/users/me/model-settings`，知识库资料使用 `/api/banks`；旧 `/api/settings` 与 `/api/knowledge-bases` 不属于当前后端契约。平台模型与检索通过管理员专用 `/api/admin/rag-settings` 维护；嵌入模型或地址变更先保存待应用值，另行提交重建后才切换，使用方法见 [设置拆分与保存反馈设计](design/设置拆分与保存反馈设计.md)。配置优先级、保存与测试规则见 [模型配置与入库流程](design/模型配置来源与普通知识库流程.md)，权限、完成情况及验收边界见 [知识库模块说明](design/知识库模块说明.md) 和[扫描 PDF 策略](design/扫描PDF云端OCR策略.md)。

对话支持快速出题、创新命题、知识答疑和数据管理四种模式；图片与数据操作确认的契约和边界见[四模式对话与主线整合](design/对话四模式与主线整合.md)。

## admin

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/admin/accounts` | List Accounts |
| `POST` | `/api/admin/accounts` | Create Account |
| `PATCH` | `/api/admin/accounts/{user_id}` | Update Account |
| `POST` | `/api/admin/accounts/{user_id}/disable` | Disable Account |
| `POST` | `/api/admin/accounts/{user_id}/reset-password` | Reset Password |
| `POST` | `/api/admin/accounts/{user_id}/restore` | Restore Account |
| `GET` | `/api/admin/overview` | Overview |
| `GET` | `/api/admin/rag-settings` | Read Settings |
| `PUT` | `/api/admin/rag-settings` | Save Settings |
| `POST` | `/api/admin/rag-settings/rebuild` | Rebuild |
| `POST` | `/api/admin/rag-settings/test` | Test Service |

## attempts

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/attempts/{attempt_id}/review` | Review Attempt |
| `POST` | `/api/attempts/{attempt_id}/submit` | Submit Attempt |
| `GET` | `/api/papers/{paper_id}/attempt` | Get Attempt |
| `POST` | `/api/papers/{paper_id}/attempts` | Start Attempt |

## auth

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/auth/config` | Auth Config |
| `POST` | `/api/auth/email-code` | Email Code |
| `POST` | `/api/auth/login/account` | Login Account |
| `POST` | `/api/auth/login/email` | Login Email |
| `POST` | `/api/auth/logout` | Logout |
| `GET` | `/api/auth/me` | Me |
| `PUT` | `/api/auth/password` | Change Password |
| `POST` | `/api/auth/password/reset` | Reset Password |
| `POST` | `/api/auth/refresh` | Refresh |

## banks

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/banks` | List Banks |
| `POST` | `/api/banks` | Create Bank |
| `POST` | `/api/banks/join` | Join Bank By Code |
| `POST` | `/api/banks/with-document` | Create Bank With Document |
| `DELETE` | `/api/banks/{bank_id}` | Delete Bank |
| `GET` | `/api/banks/{bank_id}` | Get Bank |
| `PUT` | `/api/banks/{bank_id}` | Update Bank |
| `GET` | `/api/banks/{bank_id}/members` | List Members |
| `POST` | `/api/banks/{bank_id}/members` | Add Member |
| `DELETE` | `/api/banks/{bank_id}/members/{member_id}` | Remove Member |
| `PUT` | `/api/banks/{bank_id}/members/{member_id}/role` | Set Member Role |
| `POST` | `/api/banks/{bank_id}/quit` | Quit Bank |
| `POST` | `/api/banks/{bank_id}/transfer` | Transfer Bank |

## documents

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/banks/{bank_id}/documents` | List Documents |
| `POST` | `/api/banks/{bank_id}/documents` | Upload Document |
| `DELETE` | `/api/banks/{bank_id}/documents/{document_id}` | Delete Document |
| `GET` | `/api/banks/{bank_id}/documents/{document_id}` | Get Document Status |
| `GET` | `/api/banks/{bank_id}/documents/{document_id}/download` | Download Document |
| `POST` | `/api/banks/{bank_id}/documents/{document_id}/reprocess` | Reprocess Document |
| `POST` | `/api/banks/{bank_id}/search` | Search Bank |

## chat

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/chat/sessions` | Create Session |
| `DELETE` | `/api/chat/sessions/{session_id}` | Delete Session |
| `GET` | `/api/chat/sessions/{session_id}` | Get Session |
| `POST` | `/api/chat/sessions/{session_id}/cancel` | Cancel Generation |
| `POST` | `/api/chat/sessions/{session_id}/confirm` | Confirm Operation |
| `POST` | `/api/chat/sessions/{session_id}/messages` | Send Message |
| `GET` | `/api/chat/sessions/{session_id}/progress` | Read Generation Progress |

## favorites

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/favorite-groups` | List Groups |
| `POST` | `/api/favorite-groups` | Create Group |
| `DELETE` | `/api/favorite-groups/{group_id}` | Delete Group |
| `PUT` | `/api/favorite-groups/{group_id}` | Rename Group |
| `GET` | `/api/favorites` | List Favorites |
| `POST` | `/api/favorites` | Add Favorite |
| `DELETE` | `/api/favorites/{question_id}` | Remove Favorite |
| `PUT` | `/api/favorites/{question_id}` | Move Favorite |

## generate

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/generate` | Generate Sync |
| `GET` | `/api/generate/batches/latest` | Latest Batch |
| `GET` | `/api/generate/progress/{task_id}` | Get Progress |
| `POST` | `/api/generate/start` | Start Generation |

## health

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | Health |

## notifications

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/notifications` | List Notifications |
| `POST` | `/api/notifications/read` | Mark Notifications Read |
| `DELETE` | `/api/notifications/{notification_id}` | Delete Notification |

## papers

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/papers` | List Papers |
| `POST` | `/api/papers` | Create Paper |
| `POST` | `/api/papers/batch-delete` | Batch Delete |
| `DELETE` | `/api/papers/{paper_id}` | Delete Paper |
| `GET` | `/api/papers/{paper_id}` | Get Paper |
| `PUT` | `/api/papers/{paper_id}` | Update Paper |
| `DELETE` | `/api/papers/{paper_id}/publications/{space_id}` | Remove Publication |
| `POST` | `/api/papers/{paper_id}/publications/{space_id}/resume` | Resume Publication |
| `POST` | `/api/papers/{paper_id}/publications/{space_id}/stop` | Stop Publication |
| `POST` | `/api/papers/{paper_id}/publications/{space_id}/urge` | Urge Paper |
| `POST` | `/api/papers/{paper_id}/publish` | Publish Paper |
| `POST` | `/api/papers/{paper_id}/questions/remove` | Remove Questions |
| `GET` | `/api/papers/{paper_id}/statistics` | Get Statistics |

## questions

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/questions` | List Questions |
| `POST` | `/api/questions/batch-delete` | Batch Delete |
| `DELETE` | `/api/questions/{question_id}` | Delete Question |
| `PUT` | `/api/questions/{question_id}` | Update Question |

## spaces

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/spaces` | List Spaces |
| `POST` | `/api/spaces` | Create Space |
| `POST` | `/api/spaces/join` | Join Space |
| `DELETE` | `/api/spaces/{space_id}` | Dissolve Space |
| `GET` | `/api/spaces/{space_id}` | Get Space |
| `PUT` | `/api/spaces/{space_id}` | Update Space |
| `POST` | `/api/spaces/{space_id}/leave` | Leave Space |
| `GET` | `/api/spaces/{space_id}/members` | List Members |
| `DELETE` | `/api/spaces/{space_id}/members/{user_id}` | Remove Member |
| `GET` | `/api/spaces/{space_id}/papers` | List Space Papers |

## urges

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/urges` | My Urges |
| `POST` | `/api/urges/clear` | Clear Urges |
| `DELETE` | `/api/urges/{urge_id}` | Delete Urge |
| `POST` | `/api/urges/{urge_id}/read` | Read Urge |

## users

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `PUT` | `/api/users/me` | Update Profile |
| `POST` | `/api/users/me/avatar` | Upload Avatar |
| `DELETE` | `/api/users/me/email` | Unbind Email |
| `PUT` | `/api/users/me/email` | Commit Email Change |
| `PUT` | `/api/users/me/email-binding` | Bind Email |
| `POST` | `/api/users/me/email-change` | Start Email Change |
| `GET` | `/api/users/me/model-settings` | Read Model Settings |
| `PUT` | `/api/users/me/model-settings` | Save Model Settings |
| `POST` | `/api/users/me/model-settings/test-deepseek` | Test Deepseek |
| `POST` | `/api/users/me/model-settings/test-mineru` | Test Mineru |
| `PUT` | `/api/users/me/user-no` | Change User No |

共 109 个 HTTP 操作。WebSocket 契约与启动配置见根目录 README。
