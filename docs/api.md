# MathCraft API

本文件由根目录 `openapi.json` 自动生成；运行时契约以 `/openapi.json` 和 `/docs` 为准。

后端入口为 `app.main:app`，示例地址 `http://127.0.0.1:8000`。除健康检查及公开认证流程外，受保护 HTTP 接口使用 `Authorization: Bearer <access_token>`；刷新与退出使用 HttpOnly Cookie、可信 Origin 和 `X-CSRF-Token`。

认证、资料字段、错误响应以 OpenAPI schema 为准，不再使用历史单用户设置接口。完整认证与迁移约定见 [用户系统实施规格](design/用户系统实施规格.md) 和[认证设计](design/用户系统功能规格.md)。

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
| `GET` | `/api/auth/development-account` | Development Account |
| `POST` | `/api/auth/development-account` | Development Account |
| `POST` | `/api/auth/email-code` | Email Code |
| `POST` | `/api/auth/login/email` | Login Email |
| `POST` | `/api/auth/login/password` | Login Password |
| `POST` | `/api/auth/logout` | Logout |
| `GET` | `/api/auth/me` | Me |
| `PUT` | `/api/auth/password` | Change Password |
| `POST` | `/api/auth/password/reset` | Reset Password |
| `POST` | `/api/auth/refresh` | Refresh |
| `POST` | `/api/auth/register` | Register |

## banks

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/banks` | List Banks |
| `POST` | `/api/banks` | Create Bank |
| `POST` | `/api/banks/join` | Join Bank By Code |
| `DELETE` | `/api/banks/{bank_id}` | Delete Bank |
| `GET` | `/api/banks/{bank_id}` | Get Bank |
| `PUT` | `/api/banks/{bank_id}` | Update Bank |
| `GET` | `/api/banks/{bank_id}/members` | List Members |
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
| `POST` | `/api/chat/sessions/{session_id}/messages` | Send Message |

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
| `PUT` | `/api/users/me/email` | Commit Email Change |
| `POST` | `/api/users/me/email-change` | Start Email Change |
| `GET` | `/api/users/me/model-settings` | Read Model Settings |
| `PUT` | `/api/users/me/model-settings` | Save Model Settings |
| `POST` | `/api/users/me/model-settings/test-deepseek` | Test Deepseek |
| `POST` | `/api/users/me/model-settings/test-mineru` | Test Mineru |
| `PUT` | `/api/users/me/user-no` | Change User No |

共 91 个 HTTP 操作。WebSocket 契约与启动配置见根目录 README。
