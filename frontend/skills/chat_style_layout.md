# Chat Style Layout Plan

## 目标

把当前前端改造成类似豆包 / ChatGPT 的三栏聊天工作台：

- 最左侧是对话记录列表。
- 中间是当前对话的聊天记录。
- 底部固定输入框，支持文字提问和上传附件。
- 右侧暂时不强制保留，如果代码和报告内容过多，可以作为结果抽屉或聊天消息展示。

这个阶段只做前端布局规划，不改后端接口。

## 核心结构

```text
App Shell
├── Sidebar
│   ├── User Area
│   ├── New Chat Button
│   └── Conversation List
│       └── Conversation Item
│           ├── Title
│           └── More Menu
│               ├── Rename
│               └── Delete
└── Chat Main
    ├── Chat Header
    ├── Message List
    └── Chat Composer
        ├── Attachment Button
        ├── Textarea
        └── Send Button
```

## 页面分工

### 首页 `/`

首页直接作为“新对话”页面。

需要展示：

- 左侧对话栏。
- 中间欢迎语。
- 底部输入框。
- 输入框左侧有上传附件按钮。

用户可以：

- 点击“新对话”创建一个空对话。
- 上传文档后，创建项目并跳转到项目对话页。
- 在没有上传文档时，输入框只作为引导，不直接调用后端问答。

### 项目页 `/projects/[id]`

项目页作为某个文档项目的对话页。

需要展示：

- 左侧对话栏，当前项目高亮。
- 中间聊天记录。
- 文档处理状态作为系统消息或顶部状态条。
- 报告作为 AI 消息。
- 用户提问作为用户消息。
- 文档问答结果作为 AI 消息。
- 代码产物可以作为“生成代码”消息，也可以用折叠面板展示文件列表。

## 左侧对话栏

### 新对话按钮

位置：左侧顶部。

行为：

- 点击后回到 `/`。
- 如果后续有本地会话记录，可以创建一个新的空 conversation。

### 对话列表

当前阶段先使用前端本地状态或 localStorage 保存轻量记录。

每条记录字段建议：

```ts
type Conversation = {
  id: string;
  title: string;
  projectId?: string;
  createdAt: string;
  updatedAt: string;
};
```

说明：

- `id` 是前端对话 ID。
- `projectId` 对应后端项目 ID，有上传文档后才存在。
- `title` 默认使用上传文件名，用户可以重命名。

### 更多菜单

每条对话右侧显示 `...`。

菜单动作：

- `重命名`：把列表项切换成输入框，回车或失焦保存。
- `删除`：从本地对话列表删除。

当前阶段删除只删前端本地记录，不删后端项目数据。

## 中间聊天区

### 空状态

没有项目时，中间显示：

```text
有什么我能帮你的吗？
```

下面可以放几个快捷提示：

- 上传论文并生成报告
- 分析实验方法
- 总结创新点
- 生成可运行代码

这些提示点击后填入输入框。

### 消息结构

建议统一成：

```ts
type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: string;
  status?: "pending" | "done" | "failed";
};
```

现有内容映射：

- `ProjectStatus` -> system message 或顶部状态条。
- `ReportViewer` -> assistant message。
- `QuestionPanel` 的问题 -> user message。
- `QuestionPanel` 的回答 -> assistant message。
- `CodeArtifactViewer` -> assistant message with code files。

## 底部输入框

输入框固定在中间区域底部。

布局：

```text
┌──────────────────────────────────────────────┐
│ +  输入问题，或上传文档开始分析...       发送 │
└──────────────────────────────────────────────┘
```

### 上传附件

左侧 `+` 按钮触发文件选择。

支持类型：

```text
.pdf,.docx,.txt,.md,.markdown
```

行为：

- 如果当前没有项目：上传后创建项目并跳转到 `/projects/[id]`。
- 如果当前已有项目：暂时提示“当前版本一个对话只支持一个文档”。

后续如果要支持一个对话多个附件，需要后端增加 conversation / attachments 概念。

### 发送文本

行为：

- 没有项目时：提示先上传文档。
- 项目未完成时：提示等待文档处理完成。
- 项目完成后：调用现有 `/api/projects/{project_id}/qa`。

## 组件建议

新增组件：

```text
components/AppShell.tsx
components/ConversationSidebar.tsx
components/ConversationItem.tsx
components/ChatHeader.tsx
components/ChatThread.tsx
components/ChatComposer.tsx
```

保留并改造现有组件：

```text
components/ProjectStatus.tsx
components/ReportViewer.tsx
components/QuestionPanel.tsx
components/CodeArtifactViewer.tsx
components/UploadPanel.tsx
```

更理想的方式是逐步把它们合并进新的聊天组件，但第一版可以先少动逻辑。

## 样式方向

整体风格：

- 浅色背景。
- 左侧栏宽度约 `250px`。
- 中间聊天区最大宽度约 `860px`。
- 输入框圆角较大，但不做复杂装饰。
- 对话列表紧凑，便于扫描。
- 消息气泡不需要太重，重点是阅读舒适。

布局尺寸：

```css
.app-shell {
  display: grid;
  grid-template-columns: 250px 1fr;
  height: 100vh;
}

.conversation-sidebar {
  border-right: 1px solid #e5e5e5;
  overflow: auto;
}

.chat-main {
  display: grid;
  grid-template-rows: auto 1fr auto;
  min-width: 0;
}
```

## 与当前项目的关系

当前后端只有 `project`，没有真正的 `conversation` 表。

所以第一版前端可以这样处理：

- 一个上传项目约等于一个对话。
- 对话记录先存 localStorage。
- 重命名和删除只影响本地列表。
- 后端项目数据不删除。

这样实现成本最低，也不影响现有后端。

## 后续可扩展

如果后续要做真正的多对话系统，需要后端新增：

```text
conversations
conversation_messages
conversation_attachments
```

到那时：

- 左侧对话记录从后端读取。
- 删除对话可以同步删除项目或软删除。
- 一个对话可以包含多个文档。
- 问答可以基于当前对话的所有文档检索。

## 第一版实现步骤

1. 新增本地 conversation 管理。
2. 新增左侧 `ConversationSidebar`。
3. 把首页改成空聊天页。
4. 把上传入口移动到底部 `ChatComposer`。
5. 把项目页改成聊天记录页。
6. 把报告、问答、代码产物转成聊天消息展示。
7. 保持现有 API 不变，确认上传、报告、问答、代码下载都可用。

