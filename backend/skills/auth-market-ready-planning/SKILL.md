---
name: auth-market-ready-planning
description: Plan and implement market-ready registration/login for Research Code across backend and frontend. Use when adding account auth, HttpOnly cookie sessions, user-scoped projects, user-scoped vector retrieval, protected APIs, login/register UI, authenticated workspace behavior, logout, and promotional first-screen conversion.
---

# Market-Ready Auth Planning

## 目标

把 Research Code 从本地单用户工具升级为可推广的多用户产品入口：

```text
未登录用户
  -> 看到专业、可信、有转化力的注册/登录入口

已登录用户
  -> 进入自己的论文工作空间
  -> 上传、项目、报告、代码、QA、向量索引都按 user_id 隔离
```

不要把注册登录做成孤立表单。它必须同时解决：

```text
用户转化
会话安全
项目归属
论文库隔离
向量检索隔离
前端登录态
```

## 当前事实

当前项目已经有：

```text
papers
paper_versions
projects.user_id
document_chunks.paper_id
document_chunks.paper_version_id
Qdrant payload user_id
```

但当前 `user_id` 只是临时值：

```text
local
```

做认证后必须替换为真实：

```text
users.user_id
```

否则会导致：

```text
所有用户共用 local
项目列表无法隔离
QA 可能检索到其他用户论文
跨论文扩展会混入其他用户私有论文
```

## 总体分期

按三期执行，不要一次性大改。

```text
第一期：后端认证闭环
第二期：业务接口接入 current_user
第三期：前端注册登录和市场型入口
```

## 第一期：后端认证闭环

### 目标

只实现账号和会话能力，不改上传、QA、项目业务逻辑。

完成后应该有：

```text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

### 推荐认证方式

使用 SQLite `users` + `user_sessions` + HttpOnly Cookie。

不要第一版就上复杂的 JWT access/refresh token。

登录成功后：

```text
生成随机 session_token
只写入 HttpOnly Cookie
数据库保存 token_hash
每次请求从 Cookie 取 token
hash 后查 user_sessions
得到 current_user
```

Cookie 名建议：

```text
rc_session
```

Cookie 属性建议：

```text
HttpOnly
SameSite=Lax
Path=/
Max-Age=30 days
Secure=false   # 本地开发
```

生产 HTTPS 后再启用：

```text
Secure=true
```

### 数据库表

新增 `users`：

```sql
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    avatar_initial TEXT,
    plan TEXT NOT NULL DEFAULT 'free',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

新增 `user_sessions`：

```sql
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
```

### 密码存储

不要明文保存密码。

第一版优先使用标准库：

```python
hashlib.pbkdf2_hmac()
secrets.token_bytes()
hmac.compare_digest()
```

推荐格式：

```text
pbkdf2_sha256$iterations$salt_hex$hash_hex
```

暂不引入 `passlib` 或 `bcrypt`，除非用户明确要求。

### 建议新增文件

```text
backend/app/services/auth_service.py
backend/app/core/auth.py
backend/app/api/routes_auth.py
```

### auth_service.py 职责

```python
create_user(email, password, display_name)
authenticate_user(email, password)
create_session(user_id)
get_user_by_session_token(token)
delete_session(token)
hash_password(password)
verify_password(password, password_hash)
```

### core/auth.py 职责

提供 FastAPI dependency：

```python
get_current_user(request: Request) -> User
```

未登录返回：

```text
401 unauthorized
```

### routes_auth.py 职责

实现：

```text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

注册后建议直接创建 session，让用户注册后立即进入工作台。

### 第一期预计改动文件

```text
backend/app/core/models.py
backend/app/core/database.py
backend/app/core/schemas.py
backend/app/core/auth.py
backend/app/services/auth_service.py
backend/app/api/routes_auth.py
backend/app/main.py
```

### 第一期验收

必须能完成：

```text
注册新用户
重复邮箱注册失败
错误密码登录失败
正确密码登录成功并设置 HttpOnly Cookie
/auth/me 能返回当前用户
/auth/logout 后 /auth/me 变为 401
```

## 第二期：业务接口接入 current_user

### 目标

让注册登录真正保护业务数据，而不是只有表面登录。

所有项目相关接口必须绑定和校验：

```text
project.user_id == current_user.user_id
```

否则返回：

```text
403 forbidden
```

### 必须改的接口

```text
POST /api/upload
GET  /api/projects/{project_id}
GET  /api/projects/{project_id}/report
GET  /api/projects/{project_id}/code
GET  /api/projects/{project_id}/artifact
POST /api/projects/{project_id}/qa
POST /api/projects/{project_id}/related-papers
POST /api/projects/{project_id}/reindex
```

### 上传流程修改

当前：

```text
user_id = "local"
```

改成：

```text
current_user = get_current_user()
user_id = current_user.user_id
```

上传流程：

```text
保存 PDF
  -> 计算 file_sha256
  -> find_or_create_paper_identity(file_sha256, user_id=current_user.user_id)
  -> create_project(user_id=current_user.user_id, paper_id=paper_id, file_sha256=file_sha256)
  -> create_paper_version(user_id=current_user.user_id, ...)
  -> update_project_paper_version()
  -> run_project_pipeline()
```

### document_chunks 建议补 user_id

当前 `document_chunks` 已有：

```text
paper_id
paper_version_id
```

建议新增：

```text
user_id
```

原因：

```text
Qdrant payload 要保存 user_id
QA 和跨论文检索要按 user_id 过滤
chunks 表直接带 user_id 后更容易审计和回查
```

### Qdrant 检索规则

论文内 QA：

```text
paper_version_id == current_project.paper_version_id
user_id == current_user.user_id
```

跨论文扩展：

```text
user_id == current_user.user_id
paper_id != source_paper_id
```

不要因为跨论文扩展而检索其他用户的私有论文。

### 项目列表

第二期可以顺手新增：

```text
GET /api/projects
```

只返回当前用户项目。

前端 sidebar 后续应从后端项目列表读取，而不是只用 localStorage。

### 第二期预计改动文件

```text
backend/app/api/routes_upload.py
backend/app/api/routes_projects.py
backend/app/api/routes_reports.py
backend/app/api/routes_code.py
backend/app/api/routes_qa.py
backend/app/core/database.py
backend/app/services/vector_store.py
```

### 第二期验收

必须能完成：

```text
未登录上传返回 401
用户 A 看不到用户 B 的 project
用户 A 无法访问用户 B 的 report/code/artifact/qa/reindex
上传后 projects.user_id 是真实 user_id
Qdrant payload.user_id 是真实 user_id
跨论文扩展只在当前用户论文库中检索
```

## 第三期：前端注册登录和市场型入口

### 目标

未登录用户看到有转化力的注册登录界面；登录用户进入当前聊天式工作台。

不要做冷冰冰后台登录页。

### 未登录首页

首页应表达产品价值：

```text
Research Code
Upload a paper. Get report, QA index, runnable code.
```

能力点建议：

```text
Paper to structured research brief
Ask across your paper library
Generate runnable reproduction code
```

信任点建议：

```text
Account-isolated projects and indexes
```

不要承诺：

```text
绝对安全
论文永不离开本地
完全私有
```

因为当前 LLM / embedding 可能调用外部 API。

### 登录注册体验

一个组件即可：

```text
AuthPanel
```

包含：

```text
登录 / 注册切换
email
password
display_name  # 只在注册时显示
错误提示
提交中状态
```

注册成功后直接进入工作台。

登录成功后进入工作台。

### 登录后工作台

保留现有聊天式界面：

```text
ConversationSidebar
ChatMain
ArtifactSidePanel
```

左侧用户区域显示：

```text
头像首字母
display_name 或 email
退出按钮
```

### 前端 API

`frontend/lib/api.ts` 必须给所有请求加：

```ts
credentials: "include"
```

新增：

```ts
register()
login()
logout()
getMe()
```

### 前端保护规则

```text
未登录访问首页：
  显示 AuthPanel + 产品价值入口

已登录访问首页：
  显示上传聊天工作台

未登录访问 /projects/[id]：
  引导回首页登录

已登录访问 /projects/[id]：
  正常加载项目
```

### 第三期预计改动文件

```text
frontend/lib/api.ts
frontend/app/page.tsx
frontend/app/projects/[id]/page.tsx
frontend/components/ConversationSidebar.tsx
frontend/components/AuthPanel.tsx
frontend/app/globals.css
```

### 第三期验收

必须能完成：

```text
注册后直接进入工作台
刷新页面仍保持登录
退出后回到注册登录界面
未登录不能上传论文
登录后上传请求自动带 Cookie
sidebar 显示当前用户
未登录访问项目页不会直接展示项目数据
```

## 推荐执行顺序

```text
1. 第一期开工：后端认证闭环
2. 第二期开工：业务接口接入 current_user
3. 第三期开工：前端注册登录和市场型入口
```

不要先做前端表单。

原因：

```text
如果后端没有 current_user 和业务隔离，前端登录只是装饰。
认证必须先成为后端事实源，再让前端接入。
```

## 风险和边界

- 第一版不做邮箱验证，可能存在无效邮箱注册。
- 第一版不做找回密码。
- 第一版不做第三方 OAuth。
- 第一版不做付费计划校验，`plan` 只作为预留字段。
- 开发环境 Cookie 不启用 `Secure`，生产 HTTPS 后必须启用。
- 跨端口开发时前端请求必须带 `credentials: "include"`。
- 本地开发尽量统一使用 `127.0.0.1`，避免 `localhost` 和 `127.0.0.1` 混用导致 Cookie 行为混乱。

## 完成后要写入 task_progress

每完成一期，都在 `research_code/task_progress` 中新增对应记录。
