# 029 后端认证闭环第一期

## 本期目标

按照 `auth-market-ready-planning` 第一期开工，只完成后端账号与会话闭环，不改上传、项目、报告、代码、QA 等业务接口的权限逻辑。

本期新增接口：

```text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

## 核心实现

新增 `users` 表：

```text
user_id
email
password_hash
display_name
avatar_initial
plan
created_at
updated_at
```

新增 `user_sessions` 表：

```text
session_id
user_id
token_hash
expires_at
created_at
```

认证方式：

```text
用户注册/登录成功
  -> 生成随机 session token
  -> token 明文只写入 HttpOnly Cookie: rc_session
  -> 数据库只保存 token_hash
  -> /auth/me 从 Cookie 读取 token，再用 token_hash 查询用户
```

密码存储：

```text
pbkdf2_sha256$iterations$salt_hex$hash_hex
```

当前使用 Python 标准库：

```text
hashlib.pbkdf2_hmac
secrets.token_bytes
hmac.compare_digest
```

没有新增外部依赖。

## 修改文件

```text
backend/app/core/models.py
backend/app/core/database.py
backend/app/core/schemas.py
backend/app/core/auth.py
backend/app/services/auth_service.py
backend/app/api/routes_auth.py
backend/app/main.py
```

## 行为说明

注册：

```text
email + password + display_name
  -> 创建用户
  -> 自动创建 session
  -> 返回当前用户
```

登录：

```text
email + password
  -> 校验密码
  -> 创建 session
  -> 返回当前用户
```

退出：

```text
读取 rc_session
  -> 删除数据库 session
  -> 删除浏览器 Cookie
```

当前用户：

```text
读取 rc_session
  -> session 存在且未过期，返回 user
  -> 不存在或过期，返回 401
```

## 已验证

执行过：

```text
python -m compileall .\app
```

结果：后端代码编译通过。

确认路由已注册：

```text
/api/auth/register
/api/auth/login
/api/auth/logout
/api/auth/me
```

接口链路验证结果：

```text
注册新用户 -> 200，并写入 rc_session
重复邮箱注册 -> 400 email_already_registered
错误密码登录 -> 401
/auth/me -> 200，返回当前用户
/auth/logout -> 200
退出后 /auth/me -> 401
```

验证时临时创建过 `test@example.com`，随后已从本地 SQLite 中清理该测试用户和对应 session。

## 下一期边界

第二期再做业务接口接入 `current_user`：

```text
上传接口使用真实 user_id
项目、报告、代码、artifact、QA、reindex 校验 project.user_id
Qdrant 检索过滤真实 user_id
```

本期没有提前修改这些业务权限，避免把认证闭环和业务隔离混在一起。
