---
name: retrieval-optimization-planning
description: Plan and implement mature retrieval optimization for Research Code, including Qdrant dense retrieval, query rewrite, multi-query retrieval, Graph RAG evidence expansion, neighbor expansion, section boost, hybrid search, reranking, retrieval evaluation, negative samples, and feedback-driven bad-case regression.
---

# Retrieval Optimization Planning

## 目标

把 Research Code 的检索层从“单次向量召回”升级为“多路召回、可解释、可评测、可持续优化”的生产级检索系统。

核心目标：

```text
用户问题
-> query intent / query rewrite
-> multi-query dense retrieval
-> graph evidence expansion
-> neighbor expansion
-> optional hybrid search
-> section boost / rerank
-> context assembly
-> QA / codegen
-> trace / feedback / bad case / eval regression
```

不要只调 `top_k`。检索质量问题要拆成：

```text
query 是否表达充分
召回是否覆盖 gold chunks
排序是否把 gold chunks 排前面
上下文组装是否把证据放进 prompt
LLM 是否基于证据回答
反馈是否能进入回归集
```

## 当前项目已有能力

当前已经有：

```text
Qdrant dense retrieval
论文内 search_within_paper
跨论文 search_related_papers
知识图谱 search_graph_context
QA context_orchestrator
graph_context 接入 QA prompt
retrieval_trace
feedback / bad_case
evaluation_runner
```

当前不足：

```text
query rewrite 未完整实现
multi-query retrieval 未实现
hybrid search 未实现
reranker 未实现
section boost 未实现
neighbor expansion 未实现
graph evidence chunks 未完整合并进 prompt
negative samples 未用于检索优化
真实 gold QA eval cases 不足
```

## 总体原则

1. 先建评测基线，再改检索逻辑。
2. 先做低成本高收益能力：query rewrite、multi-query、graph evidence expansion、neighbor expansion。
3. 不要一开始引入重型搜索基础设施；第一版 hybrid search 优先用 SQLite FTS5。
4. reranker 分两步：先规则轻量重排，再考虑模型 reranker。
5. Graph RAG 不能只给实体关系，还要能追溯并加载 source chunks。
6. memory 只能补充上下文，不能替代论文证据。
7. 检索改动必须通过 eval runner 证明 Recall@k / MRR 没有下降。

## 第一期：建立检索基线

### 目标

知道当前检索到底差在哪里，避免凭感觉优化。

### 要做

建立至少 50 条 retrieval eval cases，覆盖：

```text
summary
method
state space
action space
reward function
objective
dataset
experiment setup
baseline
metric
result
limitation
codegen-relevant facts
```

每条 case 至少包含：

```json
{
  "case_type": "retrieval",
  "project_id": "...",
  "paper_version_id": "...",
  "question": "这篇论文的 reward function 是什么？",
  "gold_chunk_ids": ["chunk_001", "chunk_002"],
  "recall_ks": [5, 10]
}
```

### 运行

```powershell
cd backend
python -m app.services.evaluation_runner --cases eval_cases --output ..\data\eval_reports\latest.json
```

### 指标

```text
Recall@5
Recall@10
MRR
```

### 验收标准

```text
能跑出当前检索基线
每类核心问题至少有 3-5 条 case
后续检索优化前后可以对比 Recall@k / MRR
```

## 第二期：Query Rewrite + Multi-query Retrieval

### 目标

解决“用户问法”和“论文写法”不一致导致的漏召回。

例子：

```text
用户问：reward function 是什么？

论文可能写：
objective
utility
cost
penalty
optimization target
learning objective
immediate reward
```

### 推荐新增模块

```text
backend/app/services/retrieval_query.py
```

核心接口：

```python
def build_retrieval_queries(question: str, paper_type: str | None = None) -> dict:
    return {
        "original_query": question,
        "intent": "reward",
        "expanded_queries": [
            "reward function",
            "objective function",
            "utility function",
            "cost function",
            "penalty term",
            "optimization target",
        ],
        "target_entity_types": ["reward", "objective"],
        "target_sections": ["method", "problem formulation", "mdp", "training"],
    }
```

### 重点 query rewrite 词表

reward / objective：

```text
reward function
objective function
utility function
cost function
penalty term
optimization target
learning objective
immediate reward
return
```

action：

```text
action space
action
decision variable
control action
allocation decision
scheduling decision
resource allocation decision
```

state：

```text
state space
state
observation
system state
input feature
environment state
resource utilization state
```

experiment：

```text
experimental setup
experiment setting
implementation detail
simulation setup
evaluation setup
baseline
dataset
metric
hyperparameter
```

### 检索流程

把当前单 query：

```text
search_within_paper(query=question, top_k=8)
```

升级为：

```text
build_retrieval_queries(question)
-> 对 expanded_queries 分别查 Qdrant
-> 每条 query 取 top_n
-> 合并
-> chunk_id 去重
-> 保留 source_query
-> rerank
-> 返回 top_k
```

### 推荐新增接口

```python
def search_within_paper_multi_query(
    paper_version_id: str,
    question: str,
    top_k: int = 8,
    per_query_k: int = 12,
    user_id: str = "local",
) -> dict:
    ...
```

返回：

```json
{
  "intent": "reward",
  "queries": ["reward function", "objective function", "..."],
  "hits": [
    {
      "chunk_id": "...",
      "score": 0.82,
      "source_queries": ["objective function", "cost function"],
      "section_title": "Problem Formulation"
    }
  ]
}
```

### 验收标准

```text
reward 问题即使论文写 objective / utility / cost，也能召回正确 chunk
action 问题即使论文写 decision / allocation，也能召回正确 chunk
Recall@10 比第一期基线提升
retrieval_trace 记录 rewritten_queries / intent / source_queries
```

## 第三期：Graph Evidence Expansion + Neighbor Expansion

### 目标

让知识图谱和原文证据真正闭环，并补足命中 chunk 的前后文。

### Graph Evidence Expansion

当前 Graph RAG 返回的实体和关系带有：

```text
source_chunk_ids
```

不要只把 graph_context 给 LLM。应该继续加载对应原文 chunk：

```text
graph_context
-> collect source_chunk_ids
-> list_document_chunks_by_ids
-> graph_evidence_chunks
-> merge with vector hits
-> rerank
-> prompt
```

推荐限制：

```text
graph_evidence_chunks 最多 6 个
优先 relation 的 source chunks
其次 entity 的 source chunks
低 confidence 图谱证据降权
```

### Neighbor Expansion

命中 chunk 后，根据 `order_index` 加载相邻 chunk：

```text
命中 chunk i
-> 加载 i-1 和 i+1
-> 如果同 section，可考虑 i-2 / i+2
-> 总数受 token budget 限制
```

推荐限制：

```text
每个核心 hit 最多扩展前后各 1 个
neighbor chunks 总数最多 8 个
References section 不扩展
低分 chunk 不扩展
```

### 推荐新增数据库函数

```python
def list_neighbor_document_chunks(
    project_id: str,
    order_index: int,
    window: int = 1,
    same_section: bool = True,
) -> list[dict]:
    ...
```

### 上下文合并顺序

```text
1. graph evidence chunks
2. high-score vector chunks
3. neighbor chunks
4. related paper chunks
5. project memory
6. user memory
7. conversation history
```

### 验收标准

```text
graph_context.source_chunk_ids 能进入 current_paper_chunks
公式或定义附近的问题能拿到完整上下文
retrieval_trace 记录 graph_evidence_chunk_ids / neighbor_chunk_ids
gold chunk 已召回但答案缺上下文的问题减少
```

## 第四期：Section Boost + Lightweight Rerank

### 目标

把正确 chunk 排到更靠前的位置。

### 问题类型到 section boost

reward / objective：

```text
Problem Formulation
Method
MDP
Algorithm
Training
Objective
```

action / state：

```text
Method
Problem Formulation
MDP
Environment
State Space
Action Space
```

experiment setup：

```text
Experiment
Experimental Setup
Implementation Details
Simulation Setup
Evaluation
Dataset
Baselines
```

metric / result：

```text
Evaluation Metrics
Results
Experiment
Table
Ablation
Comparison
```

### 轻量重排分数

第一版不要上复杂模型，先用可解释规则：

```text
final_score =
  vector_score * 0.55
  + keyword_overlap_score * 0.20
  + section_boost_score * 0.15
  + graph_evidence_score * 0.10
```

### 推荐新增模块

```text
backend/app/services/retrieval_reranker.py
```

核心接口：

```python
def rerank_retrieval_hits(
    question: str,
    intent: str,
    hits: list[dict],
    graph_source_chunk_ids: set[str] | None = None,
    top_k: int = 8,
) -> list[dict]:
    ...
```

### 验收标准

```text
Recall@10 不下降
MRR 提升
gold chunks 进入 top 3 的比例提升
rerank 后每个 hit 有 score breakdown
```

## 第五期：Hybrid Search

### 目标

解决术语、缩写、公式、表格、变量名等 dense embedding 不稳定的问题。

### 第一版推荐方案

优先使用 SQLite FTS5，不要第一版就引入 Elasticsearch。

新增 FTS 表：

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
    chunk_id UNINDEXED,
    project_id UNINDEXED,
    paper_version_id UNINDEXED,
    title,
    section_title,
    content
);
```

### 检索流程

```text
dense_hits = Qdrant search
keyword_hits = SQLite FTS search
merged_hits = reciprocal rank fusion
reranked_hits = lightweight rerank
```

RRF：

```text
rrf_score = 1 / (k + dense_rank) + 1 / (k + keyword_rank)
```

### 适合 hybrid 的问题

```text
A3C 是什么？
QoS metric 是什么？
Equation (7) 定义了什么？
Table II 的实验设置是什么？
CPU utilization 怎么计算？
SINR 约束是什么？
```

### 验收标准

```text
包含缩写、公式编号、表格编号、具体指标名的问题 Recall@10 提升
keyword_hits 和 dense_hits 都进入 retrieval_trace
```

## 第六期：模型 Reranker

### 目标

从“召回到了”提升到“排得准”。

### 推荐策略

分两步：

```text
第一步：规则 reranker
第二步：模型 reranker
```

模型 reranker 可选：

```text
本地 cross-encoder reranker
第三方 rerank API
embedding provider rerank endpoint
```

如果项目主要走 API，不要强依赖本地大模型。优先用可配置 provider：

```text
RERANK_PROVIDER=none | api | local
RERANK_MODEL=...
RERANK_API_KEY=...
```

### 流程

```text
multi-query + hybrid 召回 top 40 / top 80
-> reranker
-> top 8 / top 12
-> prompt
```

### 验收标准

```text
MRR 明显提升
无关 chunk 进入 prompt 的比例下降
latency 可接受
reranker 失败时自动降级到 lightweight rerank
```

## 第七期：Negative Samples + Feedback 闭环

### 目标

让用户反馈真正变成检索优化数据。

### 反馈数据

当用户反馈“chunk 不准”或内部 review 标注检索问题时，记录：

```text
question
trace_id
project_id
paper_version_id
returned_chunk_ids
bad_returned_chunk_ids
gold_chunk_ids
expected_answer_points
error_type
reviewer_note
```

### 推荐字段

在 bad case 或 eval case 中支持：

```json
{
  "positive_chunk_ids": ["chunk_10", "chunk_11"],
  "negative_chunk_ids": ["chunk_03", "chunk_07"]
}
```

### 用法

短期：

```text
作为 regression cases
用于判断修复是否有效
高频 negative section 降权
boilerplate / references 噪声降权
```

长期：

```text
训练 reranker
优化 query rewrite 词表
优化 section boost 权重
发现 chunking 问题
```

### 验收标准

```text
用户反馈能绑定 trace_id
内部 review 能补 gold_chunk_ids / negative_chunk_ids
bad case 能转成 eval case
每次检索优化后能跑 bad case regression
```

## 推荐落地顺序

严格按下面顺序做：

```text
1. 补 retrieval eval cases，建立当前基线
2. 实现 retrieval_query.py
3. 实现 multi-query dense retrieval
4. context_orchestrator 接入 multi-query
5. graph_context.source_chunk_ids 加载为 graph_evidence_chunks
6. 实现 neighbor expansion
7. 实现 lightweight reranker 和 section boost
8. 实现 SQLite FTS5 hybrid search
9. 可选接入模型 reranker
10. negative samples 接入 feedback / bad_case / eval
```

优先级：

```text
P0: eval baseline
P0: query rewrite
P0: multi-query retrieval
P0: graph evidence expansion
P0: neighbor expansion
P1: section boost
P1: lightweight rerank
P1: hybrid search
P2: model reranker
P2: negative sample training loop
```

## 关键文件建议

新增：

```text
backend/app/services/retrieval_query.py
backend/app/services/retrieval_reranker.py
backend/app/services/retrieval_fusion.py
```

可能修改：

```text
backend/app/services/vector_store.py
backend/app/services/context_orchestrator.py
backend/app/services/knowledge_graph_store.py
backend/app/core/database.py
backend/app/services/evaluation_runner.py
backend/app/services/trace_store.py
```

可选新增：

```text
backend/app/services/keyword_store.py
```

## Trace 要求

检索优化后，retrieval_trace 至少记录：

```json
{
  "intent": "reward",
  "original_query": "...",
  "rewritten_queries": ["...", "..."],
  "dense_hits": [],
  "keyword_hits": [],
  "graph_evidence_chunk_ids": [],
  "neighbor_chunk_ids": [],
  "reranked_hits": [],
  "final_chunk_ids": [],
  "score_breakdown": {}
}
```

没有 trace 的检索优化不可上线，因为 bad case 无法复现。

## 常见问题定位

gold chunk 没被召回：

```text
优先查 query rewrite / multi-query / hybrid search
```

gold chunk 被召回但排很后：

```text
优先查 reranker / section boost / fusion score
```

gold chunk 被召回但没进 prompt：

```text
优先查 context_orchestrator / token budget / context assembly
```

graph_context 命中但回答没用：

```text
优先查 graph evidence chunks 是否加载进 current_paper_chunks
```

回答混入其他论文内容：

```text
优先查 related_papers 触发规则、paper_id 过滤、memory scope
```

## 不要做的事

```text
不要只把 top_k 从 8 调到 20
不要没有 eval baseline 就大改 prompt
不要让 graph_context 替代原文 chunks
不要把 user long-term memory 当作论文事实来源
不要第一版就引入 Elasticsearch / Neo4j / 大模型 reranker
不要只看最终回答，要看 retrieval_trace
不要只修单个 bad case，不跑回归
```

## 验证命令

后端语法检查：

```powershell
cd backend
python -m compileall app
```

检索评测：

```powershell
cd backend
python -m app.services.evaluation_runner --cases eval_cases --output ..\data\eval_reports\latest.json
```

人工验收问题：

```text
这篇论文的 reward function 是什么？
这篇论文的 action space 是什么？
这篇论文的 state space 是什么？
实验设置是什么？
用了哪些 baseline？
评价指标是什么？
方法和相关论文有什么区别？
生成代码里的 action / state / reward 是否和论文一致？
```

