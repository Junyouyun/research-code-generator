---
name: memory-system-planning
description: Plan and implement Research Code memory system phases, including conversation short-term memory, project memory, user long-term memory with Qdrant, context orchestration, and frontend memory management panel.
---

# Memory System Planning

## 总目标

为 Research Code 增加可上线的记忆系统，让系统能够在不同时间、不同论文、不同项目之间保留有价值的信息，并在问答、论文分析、代码生成、代码修复等流程中稳定调用。

核心原则：

```text
conversation memory 负责当前对话连续性
project memory 负责单个论文项目的稳定事实和生成决策
user long-term memory 负责跨项目、跨论文的用户偏好和长期知识
Qdrant 负责语义召回
SQLite 负责事实存储和权限归属
context_orchestrator 负责统一调度上下文
```

不要把所有历史消息直接塞给 LLM。记忆系统必须先结构化、再检索、再裁剪，最后按任务类型组装上下文。

## 当前上下文

当前项目已经有：

```text
app/core/database.py
  SQLite 表结构和读写函数。

app/core/models.py
  User、Project、Conversation、ConversationMessage、MemoryItem 等数据模型。

app/api/routes_qa.py
  项目内 QA 入口。

app/services/project_memory.py
  项目级记忆写入和读取。

app/services/vector_store.py
  Qdrant 文档 chunk 索引、检索、重建索引。

app/services/embedding_client.py
  embedding 调用封装。

app/services/llm_paper_analyzer.py
  QA、论文分析相关 LLM 调用。
```

后续实现时优先复用这些模块，不要另起一套平行存储和检索逻辑。

## 第一步：conversation 短期记忆

目标：让每个项目的聊天问答具备短期上下文，不因为刷新页面或重新打开项目而丢失历史。

推荐落点：

```text
app/core/models.py
  Conversation
  ConversationMessage

app/core/database.py
  conversations
  conversation_messages
  get_or_create_project_conversation()
  get_conversation()
  list_conversation_messages()
  list_recent_conversation_messages()
  save_conversation_message()
  update_conversation_summary()

app/api/routes_conversations.py
  GET /api/projects/{project_id}/conversation
  GET /api/conversations/{conversation_id}/messages

app/api/routes_qa.py
  用户提问前保存 user message
  LLM 回答后保存 assistant message
  每次问答取最近 N 条消息作为短期上下文

frontend/lib/api.ts
  getProjectConversation()
  getConversationMessages()
  askProjectQuestion(projectId, question, conversationId)

frontend/app/projects/[id]/page.tsx
  页面加载时恢复 conversation 和 messages
```

实现要点：

```text
conversation 归属于 user_id，可选绑定 project_id
conversation_messages 每条消息必须带 user_id
QA 默认取最近 12 条消息
短期记忆只解决对话连续性，不负责长期偏好
不要把全部历史无限塞进 prompt
```

验收标准：

```text
刷新项目页后聊天记录仍在
继续提问时 LLM 能看到最近对话
不同用户之间不能读取彼此 conversation
```

## 第二步：project memory

目标：把单个论文项目中的稳定事实、实验决策、代码生成决策沉淀为结构化记忆，供后续 QA、代码生成、修复、重建索引使用。

推荐落点：

```text
app/core/models.py
  MemoryItem

app/core/database.py
  memory_items
  upsert_project_memory()
  list_project_memories()

app/services/project_memory.py
  record_project_memory()
  record_analysis_memory()
  record_experiment_spec_memory()
  record_code_plan_memory()
  record_validation_memory()
  get_project_memory_context()

app/api/routes_memories.py
  GET /api/projects/{project_id}/memories

app/workers/pipeline.py
  analysis 完成后写入项目记忆
  experiment_spec 完成后写入项目记忆
  code_plan 完成后写入项目记忆
  validation_result 完成后写入项目记忆

app/api/routes_qa.py
  QA 时读取 project memory，和 conversation context 一起交给 LLM
```

记忆类型建议：

```text
paper_fact
  论文标题、研究问题、方法概述、实验设置、关键结论。

experiment_decision
  论文类型、任务类型、算法、环境、数据要求、可复现实验边界。

code_generation_decision
  代码入口、模块规划、框架选择、生成文件列表。

validation_decision
  smoke test 目标、验证结果、修复次数、失败原因。
```

实现要点：

```text
scope = project
scope_id = project_id
normalized_key 用来去重和更新同一条项目事实
importance 决定上下文优先级
confidence 表示该记忆来自分析或推断的可靠程度
pipeline 里的记忆写入失败不能中断主流程
```

验收标准：

```text
新上传论文完成 pipeline 后生成项目记忆
QA prompt 中能拿到项目记忆
重复运行同一 project 时同类记忆会更新，不会无限重复堆积
```

## 第三步：user long-term memory + Qdrant

目标：沉淀跨项目、跨论文、跨会话的用户长期偏好、常用研究方向、代码风格要求、实验习惯，并用 Qdrant 做语义召回。

推荐落点：

```text
app/core/database.py
  upsert_user_memory()
  list_user_memories()
  get_memory_item()
  update_memory_item_status()
  update_memory_item_content()

app/services/user_memory.py
  record_user_memory()
  extract_user_memories_from_turn()
  get_user_memory_context()
  update_user_memory()
  archive_user_memory()

app/services/memory_vector_store.py
  index_memory_item()
  delete_memory_item_vector()
  search_user_memories()
  reindex_user_memories()

app/api/routes_memories.py
  GET /api/memories
  PATCH /api/memories/{memory_id}
  DELETE /api/memories/{memory_id}

app/api/routes_qa.py
  assistant 回答后尝试抽取长期记忆
  下一次 QA 前检索 user long-term memory
```

数据库设计：

继续复用 `memory_items` 表，不新增一张平行表。

```text
scope = user
scope_id = NULL
user_id = 当前登录用户
memory_type = user_preference | research_interest | coding_preference | workflow_preference | domain_knowledge
status = active | archived
```

长期记忆示例：

```text
user_preference
  用户希望回答更专业、具体，不要过度简单。

research_interest
  用户关注强化学习、资源分配、论文实验复现。

coding_preference
  用户倾向生成少文件、单入口、可运行 smoke test 的代码工程。

workflow_preference
  用户希望先给方案，确认后再改代码。

domain_knowledge
  用户项目使用 FastAPI、Next.js、SQLite、Qdrant、智谱 embedding-3。
```

Qdrant 设计：

```text
collection_name = memory_items_{embedding_model}_{dimensions}

payload:
  memory_id
  user_id
  scope
  scope_id
  memory_type
  content
  normalized_key
  importance
  confidence
  status
  updated_at
```

检索规则：

```text
query = 用户当前问题 + 当前任务类型
filter:
  user_id = current_user.user_id
  scope = user
  status = active

top_k 默认 6
低分结果丢弃
按 importance 和 score 综合排序
```

写入规则：

```text
只保存长期稳定信息，不保存一次性闲聊
只保存对未来任务有复用价值的信息
从 user message 和 assistant result 中抽取候选记忆
LLM 抽取结果必须返回 JSON
同 normalized_key 的记忆使用 upsert 更新，不重复插入
写入 SQLite 成功后再 upsert Qdrant
更新或删除 SQLite 记忆时同步更新或删除 Qdrant 向量
```

长期记忆抽取建议 schema：

```json
{
  "memories": [
    {
      "memory_type": "coding_preference",
      "content": "用户倾向生成少文件、单入口、可运行 smoke test 的代码工程。",
      "normalized_key": "coding:project_structure",
      "importance": 0.8,
      "confidence": 0.85,
      "reason": "用户多次表达代码生成需要可运行且不要大而空。"
    }
  ]
}
```

验收标准：

```text
用户跨项目提问时能召回长期偏好
长期记忆存在 SQLite 中，可审计、可删除
长期记忆向量存在 Qdrant 中，可语义检索
删除或归档记忆后不会再进入上下文
不同用户之间长期记忆严格隔离
```

## 第四步：context_orchestrator 统一调度

目标：把 conversation、project memory、user long-term memory、paper chunks、related paper chunks 统一调度，避免各个 API 自己拼 prompt，导致上下文不稳定。

推荐落点：

```text
app/services/context_orchestrator.py
```

核心接口：

```python
def build_qa_context(
    user_id: str,
    project_id: str,
    conversation_id: str,
    question: str,
) -> dict:
    ...
```

返回结构建议：

```json
{
  "conversation_context": [],
  "project_memory_context": [],
  "user_memory_context": [],
  "current_paper_chunks": [],
  "related_papers": [],
  "retrieval_trace": {
    "expanded": false,
    "chunk_top_k": 8,
    "memory_top_k": 6
  }
}
```

调度顺序：

```text
1. 校验 project 归属
2. 读取 conversation 最近消息
3. 读取 project memory
4. 检索 user long-term memory
5. 检索当前论文 chunks
6. 根据 query_intent 决定是否检索 related papers
7. 按预算裁剪上下文
8. 返回统一 context 给 LLM service
```

上下文优先级：

```text
用户当前问题
当前论文 chunks
project memory
近期 conversation
user long-term memory
related paper chunks
```

实现要点：

```text
routes_qa.py 只负责 HTTP、权限、保存消息、返回响应
检索、排序、裁剪、扩展判断全部放入 context_orchestrator
LLM service 只接收已经整理好的 context
context_orchestrator 要返回 retrieval_trace，方便前端和调试
```

验收标准：

```text
QA 入口不再到处散落检索逻辑
新增记忆来源时只改 context_orchestrator
回答结果能说明使用了哪些 chunks 和 memories
```

## 第五步：前端 memory 管理面板

目标：让用户能看见、编辑、删除自己的记忆，避免记忆系统变成不可控黑盒。

推荐落点：

```text
frontend/lib/api.ts
  getUserMemories()
  updateUserMemory()
  deleteUserMemory()
  getProjectMemories()

frontend/app/projects/[id]/page.tsx
  项目页右侧或设置区展示 project memory

frontend/app/settings/memory/page.tsx
  用户长期记忆管理页
```

页面能力：

```text
展示长期记忆列表
按 memory_type 筛选
搜索 memory content
编辑 content
归档或删除 memory
显示来源、更新时间、importance、confidence
显示项目级记忆，只读为主
```

交互原则：

```text
用户长期记忆必须可控
默认展示简洁内容，详情展开后再看 evidence/source
删除长期记忆后必须从 Qdrant 同步删除
编辑长期记忆后必须重新 embedding 并更新 Qdrant
项目记忆通常来自 pipeline，前端先只读，避免误改实验事实
```

验收标准：

```text
用户能查看自己的长期记忆
用户能编辑、归档、删除长期记忆
刷新页面后修改仍然存在
被归档或删除的记忆不再参与 QA 上下文
```

## 推荐实施顺序

严格按下面顺序推进：

```text
1. conversation 短期记忆
2. project memory
3. user long-term memory + Qdrant
4. context_orchestrator 统一调度
5. 前端 memory 管理面板
```

原因：

```text
短期记忆先解决聊天连续性
项目记忆先解决单项目稳定事实
长期记忆再解决跨项目偏好和知识
统一调度必须等多个上下文来源存在后再做
前端管理面板必须等后端 CRUD 和检索链路稳定后再做
```

## 不要做的事

```text
不要把所有 conversation_messages 当长期记忆
不要把 Qdrant 当事实数据库
不要让前端 localStorage 承担核心记忆
不要让每个 route 自己拼上下文
不要在没有用户隔离的情况下做跨项目记忆检索
不要把低置信度的一次性推断写成长期记忆
不要删除用户记忆时只删 SQLite，不删 Qdrant
```

## 验证命令

后端修改后至少执行：

```powershell
cd backend
python -m compileall app
```

前端修改后至少执行：

```powershell
cd frontend
npm.cmd run build
```

PowerShell 如果拦截 `npm`，使用 `npm.cmd`。
