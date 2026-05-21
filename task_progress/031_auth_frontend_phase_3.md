# 031 前端注册登录和市场型入口第三期

## 本期目标

按照 `auth-market-ready-planning` 第三期执行：让前端真正接入后端认证，未登录用户看到注册/登录入口，已登录用户进入现有聊天式工作台。

## 本期改动

### 1. 前端 API 携带 Cookie

`frontend/lib/api.ts` 中所有 `fetch` 请求已统一加入：

```text
credentials: "include"
```

新增认证 API：

```text
register()
login()
logout()
getMe()
```

新增项目列表 API：

```text
listProjects()
```

### 2. 新增 AuthPanel

新增：

```text
frontend/components/AuthPanel.tsx
```

包含：

```text
注册 / 登录切换
email
password
display_name
错误提示
提交中状态
```

注册或登录成功后，直接进入当前工作台。

### 3. 首页登录态分流

`frontend/app/page.tsx` 现在启动时调用：

```text
GET /api/auth/me
```

行为：

```text
已登录
  -> 显示原聊天式上传工作台

未登录
  -> 显示 AuthPanel + 产品价值入口
```

未登录入口表达：

```text
Research Code
Upload a paper. Get report, QA index, runnable code.
Paper to structured research brief
Ask across your paper library
Generate runnable reproduction code
```

没有承诺“论文绝对不离开本地”这类不准确表述。

### 4. 侧边栏显示用户和退出

`ConversationSidebar` 已接入：

```text
user
onLogout
```

显示：

```text
头像首字母
display_name 或 email
plan
退出登录按钮
```

退出会调用：

```text
POST /api/auth/logout
```

成功后回到首页未登录入口。

### 5. 侧边栏同步当前用户项目

登录后侧边栏会调用：

```text
GET /api/projects
```

把后端返回的当前用户项目合并进本地 conversations。

这样第三期先兼容原 localStorage 交互，后续可以再把 sidebar 完全改成服务端项目列表。

### 6. 项目页登录态保护

`frontend/app/projects/[id]/page.tsx` 现在进入时先调用：

```text
GET /api/auth/me
```

行为：

```text
未登录
  -> router.replace("/")

已登录
  -> 正常加载项目状态、报告、代码、QA
```

项目页侧边栏也显示当前用户和退出按钮。

### 7. 样式

`frontend/app/globals.css` 新增：

```text
auth-shell
auth-copy
auth-panel
auth-tabs
auth-form
auth-submit
auth-loading
sidebar-user-text
logout-button
sidebar-error
```

整体保持现有聊天工作台风格，不新增独立营销落地页。

## 修改文件

```text
frontend/lib/api.ts
frontend/app/page.tsx
frontend/app/projects/[id]/page.tsx
frontend/components/AuthPanel.tsx
frontend/components/ConversationSidebar.tsx
frontend/components/conversations.ts
frontend/app/globals.css
```

## 已验证

执行：

```text
npm.cmd run build
```

结果：通过。

Next 构建输出：

```text
Compiled successfully
Running TypeScript
Finished TypeScript
```

## 当前完整认证链路

```text
未登录访问首页
  -> AuthPanel

注册 / 登录成功
  -> 后端写 rc_session HttpOnly Cookie
  -> 前端进入上传工作台

上传论文
  -> 请求自动带 Cookie
  -> 后端写真实 user_id

访问项目页
  -> 先 /auth/me
  -> 通过后再加载项目数据

退出登录
  -> 后端删除 session
  -> 前端回到未登录入口
```

## 后续可优化

后续可以把 sidebar 从“后端项目列表合并 localStorage”升级为“完全以后端项目列表为准”，这样多设备登录时项目列表会更一致。
