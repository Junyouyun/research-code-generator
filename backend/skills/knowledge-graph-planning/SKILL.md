---
name: knowledge-graph-planning
description: Plan and implement a mature Knowledge Graph and Graph RAG system for Research Code, including graph entity/relation extraction from papers, SQLite graph storage, graph retrieval, QA orchestration, code-generation integration, frontend graph browser, and optional graph database migration.
---

# Knowledge Graph Planning

## 目标

把知识图谱作为 Research Code 的核心上下文层之一，和向量检索、项目记忆、用户长期记忆并列使用。

目标不是做一个漂亮但没用的图，而是把论文转成可检索、可追踪、可用于问答和代码生成的实体关系结构。

```text
PDF / parsed chunks
  -> paper analysis
  -> knowledge graph extraction
  -> graph_entities / graph_relations
  -> Graph RAG
  -> QA / experiment_spec / code_plan / frontend graph browser
```

核心原则：

```text
SQLite 存图谱事实
Qdrant 存语义向量
LLM 负责抽取和推理，不负责保存事实
context_orchestrator 统一调度 graph_context
每个实体和关系必须带 evidence chunk
第一版先用 SQLite，不要急着引入 Neo4j
```

## 和现有系统的关系

当前系统已有：

```text
document_chunks
  论文文本证据。

vector_store
  论文 chunks 的 Qdrant 向量检索。

project_memory
  项目级稳定事实和生成决策。

user_memory
  用户长期偏好和跨项目记忆。

context_orchestrator
  QA 上下文统一调度入口。

experiment_spec_builder / code_planner / code_generator
  论文到可运行代码的生成链路。
```

知识图谱新增的是结构化关系：

```text
Actor-Critic Agent uses Actor Network
Actor-Critic Agent uses Critic Network
Environment defines_state Resource Utilization
Environment defines_action VM Allocation
Reward Function optimizes Latency and Energy Cost
Experiment reports_metric Average Reward
CodeModule implements Environment Step
```

不要把知识图谱和 memory 混在一起：

```text
project_memory = 摘要型事实
user_memory = 用户偏好
knowledge_graph = 实体和关系
vector_store = 语义召回索引
```

## 推荐分期

严格按下面顺序推进：

```text
1. 图谱实体化：抽取实体/关系并入库
2. Graph RAG：基于问题检索实体邻域和关系路径
3. QA 接入：context_orchestrator 加 graph_context
4. 代码生成接入：experiment_spec/code_plan 使用图谱
5. 前端图谱浏览器：展示实体、关系、证据 chunks
6. 图数据库升级：可选支持 Neo4j/FalkorDB/NebulaGraph
```

不要第一期就做复杂图可视化，也不要第一期就上图数据库。第一期的核心验收是能稳定抽出有用实体和关系。

## 第一期：图谱实体化

### 目标

论文 pipeline 完成 analysis 后，自动生成知识图谱并保存。

```text
analysis + selected chunks
  -> LLM extract entities / relations
  -> normalize / merge
  -> save SQLite
  -> API view graph
```

### 数据模型

新增 dataclass：

```text
app/core/models.py
  GraphEntity
  GraphRelation
  GraphExtractionRun
```

新增 SQLite 表：

```sql
CREATE TABLE IF NOT EXISTS graph_entities (
    entity_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    paper_id TEXT,
    paper_version_id TEXT,
    entity_type TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    description TEXT,
    importance REAL NOT NULL DEFAULT 0.5,
    confidence REAL NOT NULL DEFAULT 0.7,
    source_chunk_ids TEXT,
    evidence TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

```sql
CREATE TABLE IF NOT EXISTS graph_relations (
    relation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    paper_id TEXT,
    paper_version_id TEXT,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    description TEXT,
    confidence REAL NOT NULL DEFAULT 0.7,
    source_chunk_ids TEXT,
    evidence TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_entity_id) REFERENCES graph_entities (entity_id),
    FOREIGN KEY (target_entity_id) REFERENCES graph_entities (entity_id)
)
```

```sql
CREATE TABLE IF NOT EXISTS graph_extraction_runs (
    run_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    paper_id TEXT,
    paper_version_id TEXT,
    status TEXT NOT NULL,
    entity_count INTEGER NOT NULL DEFAULT 0,
    relation_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

必要索引：

```sql
CREATE INDEX IF NOT EXISTS idx_graph_entities_project ON graph_entities (user_id, project_id, entity_type);
CREATE INDEX IF NOT EXISTS idx_graph_entities_name ON graph_entities (project_id, normalized_name);
CREATE INDEX IF NOT EXISTS idx_graph_relations_project ON graph_relations (user_id, project_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_graph_relations_source ON graph_relations (source_entity_id);
CREATE INDEX IF NOT EXISTS idx_graph_relations_target ON graph_relations (target_entity_id);
```

### 实体类型

第一版只允许这些实体类型，避免图谱污染：

```text
paper
method
algorithm
model
module
environment
state
action
reward
dataset
metric
objective
baseline
experiment
result
assumption
limitation
code_module
training_step
evaluation_protocol
```

优先抽取对问答和代码生成有价值的实体：

```text
algorithm
model
module
environment
state
action
reward
dataset
metric
objective
experiment
training_step
evaluation_protocol
code_module
```

### 关系类型

第一版只允许这些关系类型：

```text
proposes
uses
contains
depends_on
optimizes
evaluates
evaluated_on
compares_with
outperforms
reports_metric
defines_state
defines_action
defines_reward
has_component
implemented_by
requires_data
produces_output
has_limitation
trained_with
measured_by
```

对代码生成最重要：

```text
has_component
uses
depends_on
defines_state
defines_action
defines_reward
optimizes
evaluated_on
reports_metric
implemented_by
requires_data
produces_output
trained_with
measured_by
```

### 后端落点

新增：

```text
app/services/knowledge_graph_extractor.py
app/services/knowledge_graph_store.py
app/api/routes_graph.py
```

修改：

```text
app/core/models.py
app/core/database.py
app/core/schemas.py
app/main.py
app/workers/pipeline.py
```

### database.py 函数

新增：

```python
save_project_graph(project_id: str, user_id: str, graph: dict) -> dict
delete_project_graph(project_id: str, user_id: str) -> None
list_project_graph_entities(project_id: str, user_id: str) -> list[GraphEntity]
list_project_graph_relations(project_id: str, user_id: str) -> list[GraphRelation]
get_graph_entity(entity_id: str, user_id: str) -> GraphEntity | None
list_entity_relations(entity_id: str, user_id: str) -> list[GraphRelation]
record_graph_extraction_run(...) -> GraphExtractionRun
```

保存策略：

```text
每次重建某 project 的图谱时，先 delete_project_graph(project_id, user_id)
再插入新的 entities / relations
实体去重 key = project_id + entity_type + normalized_name
关系去重 key = project_id + source_entity_id + relation_type + target_entity_id
```

### 抽取服务

`knowledge_graph_extractor.py` 提供：

```python
def build_project_knowledge_graph(
    project_id: str,
    analysis: dict,
    chunks: list[dict],
) -> dict:
    ...
```

流程：

```text
1. get_project(project_id)
2. 选择高价值 chunks
3. 调 LLM 抽取 entities / relations
4. normalize entity names
5. 合并重复实体
6. 校验 relation endpoints 必须存在
7. 保存 graph
8. 返回 graph summary
```

chunk 选择规则：

```text
最多 20 个 chunks
每个 chunk 最多 1200 字
优先 section_title / hierarchy_path 命中：
  abstract
  introduction
  method
  methodology
  algorithm
  model
  experiment
  evaluation
  results
  conclusion
优先 element_type 为 paragraph/table/formula 的 chunk
```

### 抽取 Prompt 输出

LLM 必须返回 JSON：

```json
{
  "entities": [
    {
      "name": "Actor-Critic Agent",
      "entity_type": "algorithm",
      "description": "Agent that uses actor and critic networks to make resource allocation decisions.",
      "importance": 0.9,
      "confidence": 0.85,
      "source_chunk_ids": ["chunk_1"]
    }
  ],
  "relations": [
    {
      "source": "Actor-Critic Agent",
      "relation_type": "uses",
      "target": "Actor Network",
      "description": "The actor network selects allocation actions.",
      "confidence": 0.86,
      "source_chunk_ids": ["chunk_1"]
    }
  ]
}
```

Prompt 约束：

```text
Only extract entities useful for technical QA, experiment reproduction, or runnable code generation.
Do not extract generic entities such as "paper", "method", "result" unless they are specific named concepts.
Every relation source and target must refer to an extracted entity name.
Use only allowed entity_type and relation_type values.
If evidence is weak, lower confidence instead of inventing details.
```

### 验收标准

```text
上传论文并完成 pipeline 后，graph_entities 有数据
graph_relations 有数据
每条实体和关系有 source_chunk_ids
GET /api/projects/{project_id}/graph 能返回图谱
图谱抽取失败不会中断整个 pipeline，只记录 warning event
```

## 第二期：Graph RAG

### 目标

根据用户问题检索相关实体和关系，生成 `graph_context`。

新增：

```python
search_graph_context(
    project_id: str,
    user_id: str,
    query: str,
    limit_entities: int = 8,
    limit_relations: int = 20,
    depth: int = 1,
) -> dict
```

返回：

```json
{
  "entities": [
    {
      "entity_id": "...",
      "entity_type": "environment",
      "name": "Cloud Datacenter Environment",
      "description": "...",
      "source_chunk_ids": ["..."]
    }
  ],
  "relations": [
    {
      "source": "Cloud Datacenter Environment",
      "relation_type": "defines_state",
      "target": "Resource Utilization State",
      "description": "...",
      "source_chunk_ids": ["..."]
    }
  ],
  "paths": []
}
```

### 检索规则

第一版用 SQLite + 轻量打分，不用图数据库：

```text
1. query 和 entity.name / normalized_name / description 做关键词重叠
2. 根据问题意图加权 entity_type / relation_type
3. 取命中实体的一跳邻居
4. 按 confidence + importance + query_overlap 排序
```

意图映射：

```text
问 reward / 奖励：
  entity_type: reward, objective
  relation_type: defines_reward, optimizes

问 state / 状态：
  entity_type: state, environment
  relation_type: defines_state

问 action / 动作：
  entity_type: action, environment
  relation_type: defines_action

问 environment / 环境 / 仿真：
  entity_type: environment, state, action, reward
  relation_type: defines_state, defines_action, defines_reward

问 dataset / 数据：
  entity_type: dataset
  relation_type: requires_data, evaluated_on

问 metric / 指标：
  entity_type: metric, result
  relation_type: reports_metric, measured_by

问 code / 代码 / 模块：
  entity_type: code_module, module, algorithm, environment
  relation_type: implemented_by, has_component, depends_on
```

### 验收标准

```text
问 reward/state/action/environment 能命中对应图谱关系
graph_context 不为空
graph_context 每条关系能追踪 source_chunk_ids
没有图谱时 search_graph_context 返回空结构，不影响 QA
```

## 第三期：QA 接入

### 目标

把 `graph_context` 接入 `context_orchestrator` 和 QA prompt。

修改：

```text
app/services/context_orchestrator.py
app/services/llm_paper_analyzer.py
app/core/schemas.py
```

`build_qa_context()` 返回增加：

```json
{
  "graph_context": {
    "entities": [],
    "relations": [],
    "paths": []
  },
  "retrieval_trace": {
    "graph_entities": 0,
    "graph_relations": 0
  }
}
```

上下文优先级：

```text
用户当前问题
current_paper_chunks
graph_context
project_memory_context
conversation_context
user_memory_context
related_papers
```

QA prompt 要说明：

```text
graph_context contains structured entity/relation facts extracted from the current paper.
Use graph_context to explain relationships, dependencies, algorithm components, experiment structure, and code mapping.
Do not treat graph_context as separate evidence unless it has source_chunk_ids.
If graph_context conflicts with chunks, prefer chunks and mention uncertainty.
```

验收标准：

```text
QA response metadata 包含 retrieval_trace.graph_entities / graph_relations
用户问结构性问题时回答会使用图谱关系
没有图谱时 QA 仍然能走 vector chunks
```

## 第四期：代码生成接入

### 目标

让知识图谱影响实验 spec 和代码 plan，让生成代码更贴近论文结构。

修改：

```text
app/services/experiment_spec_builder.py
app/services/code_planner.py
app/services/llm_code_generator.py
```

接口升级：

```python
build_experiment_spec(analysis, chunks, graph_context=None)
plan_code_project(analysis, chunks, experiment_spec, graph_context=None)
generate_code_files(code_plan, code_dir, analysis, chunks, graph_context=None)
```

重点使用关系：

```text
defines_state
defines_action
defines_reward
has_component
uses
depends_on
implemented_by
requires_data
reports_metric
trained_with
measured_by
```

Graph 到代码映射：

```text
environment -> Environment class
state -> observation/state vector construction
action -> action space / action parser
reward -> reward function
algorithm -> Agent / Model class
model/module -> neural network or helper module
dataset -> data loader / synthetic fallback
metric -> evaluation outputs
training_step -> train loop
evaluation_protocol -> evaluate function
```

代码计划中应加入：

```json
{
  "graph_alignment": {
    "entities_used": ["..."],
    "relations_used": ["..."],
    "module_mapping": [
      {
        "entity": "Cloud Datacenter Environment",
        "target_file": "src/environment.py",
        "target_symbol": "Environment"
      }
    ]
  }
}
```

验收标准：

```text
RL 论文生成的 experiment_spec 明确包含 state/action/reward
code_plan 能说明哪些实体映射到哪些代码模块
生成代码入口仍然可 smoke run
graph 缺失时回退到原有 chunks + analysis 逻辑
```

## 第五期：前端图谱浏览器

### 目标

让用户能查看论文知识图谱和证据来源。

新增 API：

```text
GET /api/projects/{project_id}/graph
GET /api/projects/{project_id}/graph/entities/{entity_id}
```

前端修改：

```text
frontend/lib/api.ts
frontend/components/ArtifactSidePanel.tsx
frontend/app/projects/[id]/page.tsx
frontend/app/globals.css
```

第一版 UI 不做复杂 canvas，做关系浏览器：

```text
实体列表
关系列表
entity_type 筛选
relation_type 筛选
搜索实体名
点击实体展示一跳邻居
显示 source_chunk_ids
```

后续可选图可视化库：

```text
React Flow
Cytoscape.js
D3 force graph
```

验收标准：

```text
右侧 panel 有“图谱”tab
用户能看到实体和关系
能按类型筛选
点击实体能看到相关关系
能看到证据 chunk id
```

## 第六期：图数据库升级

只有当 SQLite 版图谱出现性能或功能瓶颈时再做。

可选方案：

```text
Neo4j
FalkorDB
NebulaGraph
PostgreSQL + AGE
```

升级前必须先抽象 store 接口：

```python
class KnowledgeGraphStore:
    def save_project_graph(...): ...
    def list_project_graph(...): ...
    def search_graph_context(...): ...
    def get_entity_neighborhood(...): ...
```

不要让业务层直接依赖某个图数据库 SDK。

## Pipeline 接入位置

推荐插在 analysis 后：

```text
parse document
chunk document
save chunks
index vectors
analyze paper
build knowledge graph
build report
build experiment_spec
plan code
generate code
validate code
package
```

原因：

```text
analysis 能帮助图谱抽取稳定
chunks 提供证据来源
graph 后续可以服务 report / experiment_spec / code_plan
```

如果图谱抽取失败：

```text
记录 project event warning
不要让 pipeline failed
继续生成报告和代码
```

## 质量控制

图谱抽取必须做这些校验：

```text
entity_type 必须在白名单
relation_type 必须在白名单
relation.source / relation.target 必须能映射到实体
source_chunk_ids 必须来自当前 project chunks
confidence 缺失时默认 0.7
importance 缺失时默认 0.5
空 name / 空 relation 丢弃
泛化实体丢弃，如 "method", "result", "paper" 这类无具体指向的词
```

图谱质量指标：

```text
entity_count
relation_count
relations_per_entity
entities_with_evidence_ratio
relations_with_evidence_ratio
high_confidence_relation_count
code_relevant_entity_count
```

这些指标写入 `graph_extraction_runs` 或 project event details。

## 不要做的事

```text
不要把整篇论文所有名词都抽成实体
不要把没有 source_chunk_ids 的关系当事实
不要把图谱和 user memory 混存
不要让每个 route 自己检索 graph
不要第一版就引入 Neo4j
不要为了图谱展示牺牲 QA / 代码生成主链路稳定性
不要让图谱抽取失败导致 pipeline 整体失败
```

## 验证命令

后端修改后：

```powershell
cd backend
python -m compileall app
```

前端修改后：

```powershell
cd frontend
npm.cmd run build
```

如果涉及真实 pipeline，至少用一篇小论文验证：

```text
上传 PDF
等待 pipeline completed
调用 GET /api/projects/{project_id}/graph
确认 entities / relations / source_chunk_ids 存在
问 QA：reward/state/action/environment/code module 相关问题
确认 retrieval_trace 中出现 graph_entities / graph_relations
```
