# 030 业务接口接入 current_user 第二期

## 本期目标

按照 `auth-market-ready-planning` 第二期执行：让注册登录真正保护业务数据，而不是只停留在认证接口。

核心规则：

```text
project.user_id == current_user.user_id
```

不满足时返回：

```text
403 forbidden
```

未登录访问受保护业务接口时返回：

```text
401 unauthorized
```

## 本期改动

### 1. 上传接口使用真实用户

`POST /api/upload` 已接入 `get_current_user`。

上传流程变为：

```text
读取当前登录用户
  -> 保存 PDF
  -> 计算 file_sha256
  -> find_or_create_paper_identity(file_sha256, user_id=current_user.user_id)
  -> create_project(user_id=current_user.user_id, paper_id=paper_id, file_sha256=file_sha256)
  -> create_paper_version(user_id=current_user.user_id)
  -> update_project_paper_version()
  -> 启动原 pipeline
```

这样新上传项目的 `projects.user_id` 不再是 `local`，而是真实 `users.user_id`。

### 2. 项目接口按用户隔离

新增统一项目归属校验：

```text
backend/app/core/project_access.py
```

核心逻辑：

```text
查 project
  -> 不存在返回 404
  -> project.user_id != current_user.user_id 返回 403
  -> 否则返回 project
```

已保护：

```text
GET  /api/projects/{project_id}
POST /api/projects/{project_id}/reindex
```

### 3. 新增当前用户项目列表

新增：

```text
GET /api/projects
```

只返回当前登录用户自己的项目。

这个接口后续第三期给前端 sidebar 使用，替代只依赖 localStorage 的项目列表。

### 4. 报告、代码、artifact 按用户隔离

已保护：

```text
GET /api/projects/{project_id}/report
GET /api/projects/{project_id}/code
GET /api/projects/{project_id}/artifact
```

这些接口现在会先校验项目归属，再读取磁盘文件。

### 5. QA 与跨论文检索按用户隔离

已保护：

```text
POST /api/projects/{project_id}/qa
POST /api/projects/{project_id}/related-papers
```

QA 流程中：

```text
search_within_paper(..., user_id=current_user.user_id)
```

跨论文扩展中：

```text
search_related_papers(..., user_id=current_user.user_id)
```

这样跨论文扩展只会在当前用户自己的论文库中检索，不会混入其他用户私有论文。

### 6. document_chunks 补 user_id

`document_chunks` 新增：

```text
user_id TEXT NOT NULL DEFAULT 'local'
```

保存 chunks 时从 `projects.user_id` 写入。

chunk metadata 也会带：

```text
metadata.user_id
```

### 7. Qdrant payload 必须使用真实 user_id

向量索引 payload 中：

```text
user_id
```

现在从 chunk metadata 必填读取。

如果 chunk 没有 `user_id`，索引会直接报错，避免静默写入 `local`。

## 修改文件

```text
backend/app/api/routes_upload.py
backend/app/api/routes_projects.py
backend/app/api/routes_reports.py
backend/app/api/routes_code.py
backend/app/api/routes_qa.py
backend/app/core/database.py
backend/app/core/project_access.py
backend/app/core/schemas.py
backend/app/services/vector_store.py
```

## 已验证

执行：

```text
python -m compileall .\app
```

结果：通过。

使用 FastAPI TestClient 做过最小隔离验证：

```text
未登录上传 -> 401
用户 A 访问自己的项目 -> 200
用户 B 访问用户 A 的项目 -> 403
用户 A 的项目列表 -> 只出现用户 A 的测试项目
```

验证过程中创建的测试用户和测试项目已清理：

```text
phase2_a@example.com
phase2_b@example.com
phase2_project_a
phase2_project_b
```

## 下一期边界

第三期做前端：

```text
注册/登录面板
请求携带 credentials: "include"
未登录显示市场型入口
已登录显示现有聊天工作台
sidebar 显示当前用户和项目列表
退出登录
```
