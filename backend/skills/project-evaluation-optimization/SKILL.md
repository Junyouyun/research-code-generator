---
name: project-evaluation-optimization
description: Evaluate and optimize the Research Code project with production-style evaluation sets, trace logging, bad-case classification, retrieval evaluation, Graph RAG evaluation, QA evaluation, code-generation evaluation, internal feedback loops, and regression testing. Use when improving answer quality, retrieval quality, knowledge graph quality, report quality, generated code quality, or when analyzing user feedback and bad cases.
---

# Project Evaluation Optimization

## 目标

把 Research Code 的优化从“凭感觉调 prompt / top_k”改成可复现的工程闭环：

```text
用户反馈 / 内部反馈
-> bad case
-> trace 定位
-> 错误分类
-> 修对应模块
-> 回归测评
-> 指标提升后上线
```

核心原则：

```text
不要只看最终回答。
要把一次结果拆成：PDF 解析、chunking、retrieval、graph_context、context assembly、LLM generation、code validation。
第一次出错的层，就是优先修复层。
```

## 需要测评的模块

Research Code 不是普通聊天系统，至少要测这些模块：

```text
1. PDF 解析质量
2. chunk 切分质量
3. 向量检索质量
4. 知识图谱抽取质量
5. Graph RAG QA 质量
6. 报告总结质量
7. 代码生成质量
8. 代码可运行验证质量
9. memory 使用质量
10. 前端用户体验
```

## 测评集类型

### 1. PDF 解析测评

测：

```text
PDF 文本是否完整
公式 / 表格 / 图注是否丢失
章节标题是否识别
页码是否保留
双栏论文顺序是否错乱
References 是否混入正文
```

指标：

```text
parse_coverage
section_detect_rate
table_caption_detect_rate
broken_text_ratio
```

常见 bad case：

```text
表格丢失
公式乱码
双栏论文顺序错乱
正文和参考文献混在一起
实验设置被解析成碎片
```

优化方向：

```text
更好的 PDF parser
section-aware parsing
table / caption 特殊提取
正文 / reference 分离
页码和 section metadata 保留
```

### 2. 检索测评

测：

```text
用户问一个问题，系统能否召回包含答案的 chunks。
```

样本格式：

```json
{
  "question": "这篇论文的 action space 是什么？",
  "gold_chunk_ids": ["chunk_23", "chunk_24"],
  "type": "action_space"
}
```

指标：

```text
Recall@5
Recall@10
MRR
nDCG
answer_chunk_coverage
```

判断：

```text
gold chunk 没进 top-k -> retrieval miss
gold chunk 排名靠后 -> ranking weak
召回很多无关 chunks -> retrieval noise
```

### 3. 知识图谱测评

测：

```text
实体是否具体
关系是否正确
source_chunk_ids 是否真实支撑实体和关系
是否存在大量泛化实体
```

样本格式：

```json
{
  "paper_id": "...",
  "expected_entities": [
    {"name": "VM Allocation Decision", "type": "action"},
    {"name": "Resource Utilization", "type": "metric"}
  ],
  "expected_relations": [
    {
      "source": "CloudDatacenterEnv",
      "relation": "defines_action",
      "target": "VM Allocation Decision"
    }
  ]
}
```

指标：

```text
entity_precision
entity_recall
relation_precision
relation_recall
source_chunk_coverage
generic_entity_ratio
orphan_entity_ratio
```

重点：

```text
generic_entity_ratio 高，说明抽出了 paper / method / result / model 这类低价值实体。
source_chunk_coverage 低，说明图谱证据链不可靠。
```

### 4. QA 测评

测：

```text
回答是否准确
回答是否有原文证据
回答是否覆盖关键点
回答是否承认不确定
是否存在幻觉
```

样本格式：

```json
{
  "question": "reward function 是什么？",
  "expected_answer_points": [
    "包含 resource utilization",
    "包含 SLA violation penalty",
    "论文没有给出完整公式"
  ],
  "must_cite_chunks": ["chunk_18", "chunk_19"]
}
```

指标：

```text
answer_correctness
evidence_support
hallucination_rate
uncertainty_handling
citation_accuracy
```

人工评分：

```text
0 = 错
1 = 部分对
2 = 基本对
3 = 准确、有证据、知道不确定边界
```

### 5. 代码生成测评

测：

```text
生成代码是否能运行
模块契约是否一致
入口是否稳定
state/action/reward 是否贴近论文
算法、metric、dataset 是否和 experiment_spec 一致
```

指标：

```text
build_success_rate
smoke_run_success_rate
repair_success_rate
repair_rounds_avg
contract_pass_rate
semantic_alignment_score
```

重点：

```text
能跑 != 符合论文。
需要 semantic validation 检查 state/action/reward/metric 是否和 experiment_spec、graph_context、chunks 对齐。
```

## Trace Logging

所有 QA、报告、代码生成都要保存 trace。没有 trace，bad case 无法定位。

QA trace 至少保存：

```text
user_id
project_id
paper_version_id
question
answer
user_feedback
rewritten_query
retrieved_chunks
retrieval_scores
graph_context
source_chunk_ids
project_memory
user_memory
final_prompt_hash
model_name
latency
token_usage
created_at
```

代码生成 trace 至少保存：

```text
project_id
paper_version_id
analysis
retrieved_chunks
graph_context
experiment_spec
code_plan
generated_files
validation_command
validation_result
validation_error
repair_attempts
final_status
```

## Bad Case 分类

每个用户反馈或内部反馈都要分类。推荐错误类型：

```text
PDF_PARSE_ERROR
CHUNKING_ERROR
RETRIEVAL_MISS
RETRIEVAL_NOISE
GRAPH_MISSING
GRAPH_WRONG
CONTEXT_ASSEMBLY_ERROR
PROMPT_ERROR
LLM_HALLUCINATION
MEMORY_POLLUTION
CROSS_PAPER_POLLUTION
PAPER_AMBIGUOUS
CODE_CONTRACT_ERROR
CODE_IMPLEMENTATION_ERROR
VALIDATION_GAP
```

定位规则：

```text
gold chunk 没召回
-> RETRIEVAL_MISS

gold chunk 召回了但没进 prompt
-> CONTEXT_ASSEMBLY_ERROR

gold chunk 进 prompt 了但回答错
-> PROMPT_ERROR / LLM_HALLUCINATION

graph 抽错并误导回答
-> GRAPH_WRONG

回答混入其他论文
-> MEMORY_POLLUTION / CROSS_PAPER_POLLUTION

论文没明确写，系统硬答
-> PAPER_AMBIGUOUS / UNCERTAINTY_HANDLING_ERROR

代码能跑但 state/action/reward 不符论文
-> VALIDATION_GAP / CODE_IMPLEMENTATION_ERROR
```

## 内部反馈流程

内部反馈不要只标“好 / 不好”。每条反馈至少包含：

```json
{
  "case_id": "...",
  "question": "...",
  "answer_score": 1,
  "error_type": "RETRIEVAL_MISS",
  "missing_gold_chunks": ["chunk_18"],
  "comment": "reward 在 objective function 段落，检索未召回"
}
```

处理流程：

```text
用户反馈 / 内部反馈
-> 建 bad case
-> 标 error_type
-> 标 gold chunks / expected answer points
-> 加入 eval set
-> 修模块
-> 跑 regression
```

禁止：

```text
只修一个 case 就上线。
没有回归集时改 prompt / retrieval。
```

## 检索优化

检索优化不能只调 top_k。按以下顺序处理。

### 1. Query Rewrite

把短问题扩成论文常用表达。

示例：

```text
reward function 是什么？
->
reward function, objective function, utility function, cost function, penalty term, optimization target

action space 是什么？
->
action space, decision variable, control action, allocation decision, scheduling decision

state space 是什么？
->
state space, observation, system state, input features
```

作用：

```text
解决论文不用用户原词的问题。
```

### 2. Multi-query Retrieval

一个问题生成多个检索 query。

示例：

```text
用户问题：reward function 是什么？

query_1: reward function in reinforcement learning formulation
query_2: objective function and penalty terms
query_3: optimization target resource allocation
query_4: utility function SLA energy resource utilization
```

流程：

```text
multi queries
-> each query top-k
-> merge
-> dedupe
-> rerank
```

### 3. Hybrid Search

组合：

```text
dense embedding search
+ BM25 keyword search
```

原因：

```text
公式名、算法缩写、指标名、超参数，BM25 经常比 embedding 更稳。
```

打分示例：

```text
hybrid_score = dense_score * 0.6 + bm25_score * 0.4
```

### 4. Reranker

流程：

```text
Qdrant 召回 top 50
-> cross-encoder reranker
-> 取 top 8
```

收益：

```text
embedding 负责召回
reranker 负责精排
减少无关 chunk 进 prompt
```

### 5. Metadata Filter / Boost

按问题类型提升 section 权重。

```text
reward/action/state:
Problem Formulation, Method, MDP, Algorithm

实验设置:
Experiments, Experimental Setup, Implementation Details, Evaluation

结果问题:
Results, Ablation, Table captions
```

打分：

```text
score = embedding_score + keyword_score + section_score + table_score
```

### 6. Neighbor Expansion

命中 chunk 后加入邻近 chunk：

```text
chunk_24 命中
-> 加 chunk_23 和 chunk_25
```

原因：

```text
定义可能跨段，前一段介绍变量，后一段给公式。
```

### 7. Graph Evidence Expansion

Graph 命中实体关系后，读取其证据 chunk：

```text
graph_context.source_chunk_ids
-> 从 DB 读取对应 chunks
-> 合并到 retrieved_chunks
-> 去重
-> rerank / reorder
-> prompt
```

这是当前项目优先级很高的优化。

### 8. MMR 多样性

避免 top-k 全来自同一段附近。

```text
MMR = relevance + diversity
```

适合：

```text
长论文
多章节答案
实验设置分散
```

### 9. Section-level Retrieval

先找 section，再找 chunk。

```text
query
-> section retrieval
-> chunk retrieval inside section
```

适合：

```text
Experimental Setup
Implementation Details
Results
```

### 10. 负样本积累

把 bad case 中误召回 chunks 记录为 negative：

```text
question
positive_chunk_ids
negative_chunk_ids
```

用途：

```text
reranker training
retrieval regression
prompt tuning
```

## 非检索优化

### Chunking 优化

问题：

```text
答案跨 chunk
chunk 太短丢上下文
chunk 太长噪声多
section metadata 丢失
```

优化：

```text
section-aware chunking
page / section / subsection metadata
chunk overlap
neighbor chunk expansion
table / caption 独立 chunk
References 排除
```

### Context Assembly 优化

常见问题：

```text
检索到了正确 chunk，但没放进 prompt。
graph_context 有 source_chunk_ids，但 source chunks 没进 prompt。
memory 抢占 token，论文证据被截断。
```

推荐 prompt 证据顺序：

```text
1. gold / graph evidence chunks
2. reranked top chunks
3. project memory
4. user preference memory
5. conversation history
```

### Graph Context 优化

优化点：

```text
schema-specific extraction
source_chunk_ids 强校验
generic entity filter
gap-filling re-extraction
low-confidence relation 降权
```

### Prompt 优化

不要只写更长 prompt。加硬约束：

```text
必须基于 evidence 回答
chunks 是事实源，graph_context 是结构辅助
冲突时 chunks 优先
没有明确证据就说不明确
不能编公式
必须区分原文明确写 vs 系统推断
```

### Answer Verifier

回答后再检查：

```text
answer + chunks + graph_context
-> verifier
-> 判断是否回答问题、是否有证据、是否幻觉、是否太泛
-> 不通过则重答
```

### Memory 优化

原则：

```text
user long-term memory 只放用户偏好，不放论文事实。
project memory 只限当前 project。
跨论文内容必须显式标注来源。
QA 中论文证据优先于 memory。
```

## 代码生成专项测评

对代码生成，至少拆成这些层：

```text
analysis
-> graph_context
-> experiment_spec
-> code_plan
-> generated files
-> validation
-> repair
```

定位规则：

```text
论文原文 action 正确，但 retrieval 没召回
-> RETRIEVAL_MISS

retrieval 正确，但 graph action 抽错
-> GRAPH_WRONG

retrieval + graph 正确，但 experiment_spec.action_space 错
-> SPEC_ERROR

spec 正确，但 code_plan 把连续动作规划成离散动作
-> CODE_PLAN_ERROR

code_plan 正确，但 environment.py 实现错
-> CODE_IMPLEMENTATION_ERROR

代码错但 smoke test 通过
-> VALIDATION_GAP
```

必须区分：

```text
can_run
semantic_alignment
```

代码能运行，只说明工程闭环没断；不说明贴合论文。

## 最小落地顺序

### 第一期：Trace Logging

先保存：

```text
question
answer
retrieved_chunks
retrieval_scores
graph_context
final_prompt_hash
model
latency
feedback
```

### 第二期：50 个黄金 QA 样本

覆盖：

```text
summary
method
state
action
reward
dataset
metric
baseline
experiment
codegen
```

每个样本标：

```text
question
expected_answer_points
gold_chunk_ids
question_type
```

### 第三期：Retrieval Eval

跑：

```text
Recall@5
Recall@10
MRR
```

先判断检索是否是主要瓶颈。

### 第四期：Graph Evidence Chunks

实现：

```text
graph_context.source_chunk_ids
-> load chunks
-> merge into prompt
```

### 第五期：Reranker

实现：

```text
Qdrant top50
-> reranker top8
```

### 第六期：Answer Verifier

实现：

```text
answer
-> evidence check
-> hallucination check
-> uncertainty check
```

## 每次优化前后的回归检查

每次改 retrieval、prompt、graph、context assembly、memory、codegen，都要跑：

```text
retrieval eval
QA eval
graph eval
codegen smoke eval
bad case regression
```

上线标准：

```text
核心指标提升
已有 bad case 不回退
新错误可解释
trace 可复现
```

## 最终判断表

```text
gold chunk 没召回
-> 检索问题

gold chunk 召回了但没进 prompt
-> 上下文组装问题

gold chunk 进 prompt 了但答错
-> prompt / LLM 生成问题

graph 抽错并误导回答
-> 知识图谱问题

回答混入别的论文
-> memory / cross-paper scope 问题

论文没明确写但系统硬答
-> uncertainty handling 问题

代码能跑但语义不符论文
-> semantic validation 不足
```

## 优先级建议

优先做：

```text
1. trace logging
2. bad case 标注
3. retrieval eval
4. graph source chunks 合并进 prompt
5. query rewrite
6. hybrid search
7. reranker
8. answer verifier
9. graph gap-filling
10. memory scope 限制
```

不要一开始做：

```text
LoRA / SFT / RL
复杂 multi-agent
没有 eval set 的大规模 prompt 重写
没有 trace 的盲目 top_k 调参
```

