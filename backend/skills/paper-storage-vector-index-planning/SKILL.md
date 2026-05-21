---
name: paper-storage-vector-index-planning
description: Plan and implement paper ingestion storage for Research Code: entity database first, vector database second, per-user/per-paper indexing, chunk persistence, embedding upsert, retrieval, reindexing, and QA/code-generation retrieval integration.
---

# 论文实体库与向量库规划

## 目标

为用户上传论文增加可靠的存储与检索流程：

```text
用户上传论文
  -> 保存原始文件
  -> 在实体数据库创建 project 记录
  -> 解析论文为 elements
  -> 切分为 chunks
  -> 保存 chunks 到实体数据库
  -> 为 chunks 生成 embeddings
  -> upsert vectors 到向量数据库
  -> QA、论文分析、代码生成使用向量检索拿相关 chunks
```

核心原则：

```text
实体数据库是事实源。
向量数据库是检索索引。
```

不要把向量数据库当成论文正文、项目状态、用户归属的唯一存储位置。

## 当前项目状态

当前后端已经有实体数据库，使用 SQLite。

关键文件：

```text
app/api/routes_upload.py
  接收上传文件，创建 workspace，保存文件，创建 project 行，启动后台 pipeline。

app/core/storage.py
  create_project_workspace() 使用 uuid4().hex 生成 project_id。
  这意味着每次上传默认都是一个新的 project_id。

app/core/database.py
  负责 SQLite 表和数据库读写函数。
  已有表：
    projects
    document_chunks
    project_events

app/workers/pipeline.py
  执行 parse -> chunk -> save chunks -> analyze -> report -> code generation -> validation -> packaging。

app/api/routes_qa.py
  当前 QA 会读取某个 project_id 下的全部 document_chunks，然后交给 LLM。
  目前还没有使用向量检索。
```

当前系统已经把 chunk 文本保存到了 `document_chunks`。向量库应该加在这个步骤之后，而不是替代它。

## 关于同一篇论文再次上传

当前项目**不能自动识别同一篇论文再次上传**。

原因是：

```python
project_id = uuid4().hex
```

`project_id` 是每次上传时随机生成的新 ID，不是基于文件内容、论文标题、文件名或用户生成的。

所以当前含义是：

```text
同一个 project_id 重新处理：
  会删除该 project_id 下的旧 chunks，再插入新 chunks。

同一篇论文再次上传：
  会生成新的 project_id。
  会被当成一个全新的项目。
  不会自动删除上一次上传产生的 chunks。
```

`save_document_chunks(project_id, chunks)` 里的：

```sql
DELETE FROM document_chunks WHERE project_id = ?
```

只能删除**当前 project_id** 对应的 chunks。它识别不了“这是不是同一篇论文”，它只知道“这是不是同一个项目”。

如果后续需要识别同一篇论文，需要额外增加：

```text
file_sha256
user_id
paper_fingerprint
```

推荐最小规则：

```text
同一个 user_id 下，file_sha256 相同，认为是同一个原始文件。
```

但是否复用旧 project、创建新版本、还是拒绝重复上传，是产品策略问题，不应该由 `project_id` 随机值承担。

## 默认采用策略四：版本化论文库

后续系统需要支持“从论文 A 发散检索相关论文 B/C/D”，因此默认采用策略四：版本化论文库。

不要把“一次上传”直接等同于“一篇论文”。推荐拆成三层：

```text
paper_id
  代表论文本身，例如论文 A。

paper_version_id
  代表论文 A 的某个上传、解析、切分、索引版本。

project_id
  代表用户围绕某个 paper_version 发起的一次处理任务，例如分析、问答、代码生成。
```

三者关系：

```text
一篇 paper 可以有多个 paper_versions。
一个 paper_version 可以对应一个或多个 projects。
一个 project 绑定一个明确的 paper_version。
```

这样做的原因：

```text
同一篇论文重复上传时，不会丢失历史处理结果。
不同解析器、chunker、embedding 模型产生的版本可以并存。
论文内 QA 可以锁定当前版本。
跨论文发散检索可以排除同一个 paper_id，避免检索结果全是自己。
```

推荐实体关系：

```text
papers
  paper_id
  canonical_title
  normalized_title
  authors
  doi
  arxiv_id
  abstract
  year
  venue
  created_at
  updated_at

paper_versions
  paper_version_id
  paper_id
  user_id
  project_id
  file_sha256
  original_filename
  pdf_path
  parser_version
  chunker_version
  embedding_model
  version_number
  created_at

projects
  project_id
  user_id
  paper_id
  paper_version_id
  status
  current_step
  progress
  error_message
  created_at
  updated_at

document_chunks
  chunk_id
  project_id
  paper_id
  paper_version_id
  content
  content_hash
  section_title
  hierarchy_path
  page_start
  page_end
  order_index
  created_at
```

向量库 metadata 必须同时保存：

```text
user_id
project_id
paper_id
paper_version_id
chunk_id
content_hash
embedding_model
section_title
page_start
page_end
order_index
```

### 论文身份识别规则

论文身份识别不要只依赖 `file_sha256`。

推荐优先级：

```text
doi 相同 -> 同一篇论文
arxiv_id 相同 -> 同一篇论文
normalized_title + authors 高度相似 -> 可能是同一篇论文
file_sha256 相同 -> 同一个 PDF 文件
```

注意：

```text
file_sha256 相同，一定是同一个文件。
file_sha256 不同，不代表不是同一篇论文。
```

因为同一篇论文可能有：

```text
arXiv 版
会议版
作者上传版
带水印版
扫描版
新版 PDF
```

推荐落地规则：

```text
paper_id 由 doi/arxiv_id/title+authors 这类论文身份信息决定。
paper_version_id 由 file_sha256 + parser_version + chunker_version + embedding_model 决定。
project_id 仍然可以使用 uuid4().hex，表示一次处理任务。
```

### 论文内检索与跨论文检索必须分开

论文内 QA：

```text
search_within_paper(
    paper_version_id: str,
    query: str,
    top_k: int = 8,
)
```

过滤条件：

```text
paper_version_id == 当前版本
```

用途：

```text
论文 A 的方法是什么？
论文 A 的实验设置是什么？
论文 A 有没有开源代码？
```

跨论文发散检索：

```text
search_related_papers(
    source_paper_id: str,
    query: str,
    top_papers: int = 5,
    chunks_per_paper: int = 3,
)
```

过滤条件：

```text
paper_id != source_paper_id
user_id == current_user_id 或 corpus_scope == public
```

用途：

```text
和论文 A 方法相似的论文有哪些？
论文 A 可以扩展到哪些方向？
论文 B/C 能否补充论文 A 的不足？
```

### 跨论文检索必须按 paper_id 分组

向量库天然返回 chunks，不是论文。跨论文发散时不要直接返回 top chunks。

推荐流程：

```text
1. 使用 query embedding 召回 top 80 chunks。
2. 过滤掉 source_paper_id 自己。
3. 按 paper_id 分组。
4. 每篇论文最多保留 chunks_per_paper 个 chunks。
5. 计算 paper-level score。
6. 返回 top_papers 篇不同论文。
```

这样可以避免某一篇相似论文或同一篇论文的多个版本霸占结果。

推荐返回结构：

```json
{
  "paper_id": "...",
  "title": "...",
  "score": 0.82,
  "reason": "方法同样使用强化学习进行资源调度",
  "chunks": [
    {
      "chunk_id": "...",
      "content": "...",
      "page_start": 3,
      "section_title": "Method"
    }
  ]
}
```

### 同一篇论文不同版本的检索规则

同一篇论文的多个版本应该共享同一个 `paper_id`，但拥有不同的 `paper_version_id`。

示例：

```text
paper_id = paper_A

paper_version_id = A_v1
  第一次上传
  parser_version = 2026-05-18
  embedding_model = text-embedding-3-small

paper_version_id = A_v2
  第二次上传
  chunker_version = new_chunker
  embedding_model = text-embedding-3-large
```

论文内 QA 默认查当前项目绑定的版本：

```text
paper_version_id == A_v2
```

跨论文发散检索默认排除整篇论文：

```text
paper_id != paper_A
```

这样 A_v1、A_v2、A_v3 不会冒充“相关论文”出现在发散结果里。

## 为什么实体数据库必须先做

实体数据库保存的是必须可靠、可检查、可恢复的事实：

- 哪个用户上传了哪篇论文。
- 哪个 project 对应哪次上传。
- 原始文件保存在哪里。
- 当前处理状态和进度是什么。
- 解析出了哪些 chunks。
- 每个 chunk 的页码、章节、顺序和内容是什么。
- pipeline 过程中发生了哪些事件和错误。
- 下游系统使用的标准 `chunk_id` 是什么。

这些信息必须先于向量库存在。原因是向量库适合做语义相似度搜索，不适合承担事务状态、项目生命周期和审计记录。

如果向量库失败，系统仍然应该知道：

```text
project 存在
原始文件存在
chunks 已经保存
后面可以重试向量索引
```

如果实体库缺失，只剩向量库，系统无法可靠回答：

```text
这些 vectors 属于哪个用户？
这些 vectors 来自哪个文件？
前端应该显示哪个上传状态？
哪些 chunks 应该删除或重建？
```

## 实体数据库入库流程

上传论文时使用这个流程：

```text
POST /api/upload
  -> create_project_workspace()
  -> save_upload_file()
  -> create_project()
  -> background_tasks.add_task(run_project_pipeline)
```

然后 pipeline 继续：

```text
run_project_pipeline(project_id, document_path)
  -> load_document_elements()
  -> 写入 parsed elements JSON
  -> elements_to_parsed_paper()
  -> chunk_document_elements()
  -> save_document_chunks(project_id, chunks)
  -> list_document_chunks(project_id)
  -> analyze_paper_with_llm()
  -> generate report/code/artifact
```

### 步骤说明

1. 创建 workspace 和 `project_id`。

```text
原因：
后续所有产物都需要一个稳定 ID：
uploads、parsed files、chunks、generated code、report、zip、events、vectors。
```

2. 保存原始上传文件。

```text
原因：
原始文件是证据源。后面解析、切分、向量化逻辑变化时，可以从原始论文重新处理。
```

3. 插入 `projects` 表。

推荐字段：

```text
project_id
user_id              # 有多用户登录后再加，前期可以 nullable
paper_id             # 策略四需要
paper_version_id     # 策略四需要
status
current_step
progress
original_filename
pdf_path
file_sha256          # 推荐增加，用于识别重复文件
paper_title          # 解析后可选回填
error_message
created_at
updated_at
```

原因：

```text
前端需要立即拿到项目状态。
后端需要知道项目归属和生命周期。
重试任务需要知道这是新项目还是已有项目。
```

4. 解析论文为 elements。

推荐 element metadata：

```text
document_id/project_id
element_id
type
text
markdown
page_start
page_end
section_title
hierarchy_path
order_index
source_file_type
needs_review
```

原因：

```text
elements 保存的是 chunk 之前的文档结构。
后续 chunk 策略变化时，可以基于 elements 或原始文件重新生成 chunks。
```

5. 切分 elements 为 chunks。

推荐 chunk metadata：

```text
chunk_id
project_id
content
document_title
section_title
hierarchy_path
page_start
page_end
element_type
chunk_size_tokens
is_special_element
is_cross_page
is_split_sentence
is_forced_split
needs_review
source_file_type
order_index
created_at
content_hash          # 推荐增加，用于判断 chunk 内容是否变化
```

原因：

```text
LLM 上下文窗口有限，不能直接塞整篇论文。
向量检索需要稳定的检索单元。
页码和章节信息用于引用、调试和展示来源。
```

6. 保存 chunks 到 `document_chunks`。

当前简单策略是按 `project_id` 全量替换：

```sql
DELETE FROM document_chunks WHERE project_id = ?
INSERT all chunks ordered by order_index
```

原因：

```text
在当前项目规模下，全量替换更简单、更可靠。
当同一个 project 被重新处理时，可以避免旧 chunks 残留。
实体库保存完整 chunks 后，向量库也可以基于它重建。
```

注意：

```text
这不是“自动识别同一篇论文”。
它只是“清空同一个 project_id 的旧 chunks”。
```

更大规模后，可以切换为基于 hash 的增量更新：

```text
content_hash 相同 -> 保留
content_hash 新增 -> insert/upsert
旧 content_hash 消失 -> delete
```

## 向量数据库的职责

向量数据库保存 chunk embeddings，用来做语义检索。

它应该回答：

```text
给定一个问题或生成任务，哪些 chunks 在语义上最相关？
```

它不应该负责：

```text
project status
raw file storage
full source text authority
user ownership
pipeline state
audit trail
```

这些属于实体数据库。

## 向量数据库入库流程

向量索引应该在 chunks 已经保存进实体数据库之后执行。

推荐顺序：

```text
chunks = chunk_document_elements(elements)
save_document_chunks(project_id, chunks)
db_chunks = list_document_chunks(project_id)
index_document_chunks(project_id, db_chunks)
```

这个顺序很重要：

```text
应该使用 db_chunks，而不是内存里的 raw chunks。
这样向量库 metadata 和实体数据库最终提交的数据一致。
```

### 步骤说明

1. 准备 embedding 输入。

每个 chunk 默认使用：

```text
embedding_text = chunk.content
```

也可以适度加结构信息：

```text
Title: {document_title}
Section: {section_title}
Page: {page_start}-{page_end}
Content:
{content}
```

原因：

```text
embedding 需要捕捉正文语义，也可以适当知道章节上下文。
但 metadata 前缀不要太多，否则会稀释正文语义。
```

2. 批量生成 embeddings。

推荐新增服务：

```text
app/services/embedding_client.py
  embed_texts(texts: list[str]) -> list[list[float]]
```

推荐配置：

```text
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_BATCH_SIZE=64
EMBEDDING_TIMEOUT_SECONDS=60
```

原因：

```text
批处理可以减少网络请求开销。
embedding client 独立出来，可以避免和 chat completion 代码混在一起。
```

3. 写入向量库。

每条 vector 使用稳定 ID：

```text
vector_id = chunk_id
```

metadata 推荐：

```text
project_id
paper_id
paper_version_id
user_id
chunk_id
document_title
section_title
hierarchy_path
page_start
page_end
element_type
order_index
content_hash
embedding_model
created_at
```

原因：

```text
project_id/user_id 用于隔离用户和项目，防止串数据。
chunk_id 用于从向量检索结果回查实体库。
content_hash 用于判断是否需要重建索引。
embedding_model 用于未来升级 embedding 模型。
```

4. 在实体库记录索引状态。

新增轻量表：

```sql
CREATE TABLE IF NOT EXISTS vector_index_records (
    chunk_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    paper_version_id TEXT NOT NULL,
    vector_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    vector_store TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);
```

原因：

```text
实体库应该知道哪些 chunks 已经被索引。
这样才能做重试、审计和 reindex。
向量库是索引，实体库记录索引状态。
```

5. 记录 project 状态和事件。

建议增加状态：

```text
INDEXING_VECTORS = "indexing_vectors"
```

建议记录事件：

```text
vector_indexing started
embedded N chunks
upserted N vectors
vector_indexing completed
```

原因：

```text
前端需要展示后端正在做什么。
向量索引可能独立失败，需要单独可见。
```

## 检索流程

QA 应该使用向量检索，而不是把某个项目的全部 chunks 都发送给 LLM。

当前 QA 流程：

```text
question
  -> list_document_chunks(project_id)
  -> answer_question_with_chunks(question, all_chunks)
```

目标 QA 流程：

```text
question
  -> embed question
  -> vector search with filter paper_version_id + user_id
  -> get top_k chunk_ids
  -> load exact chunks from document_chunks by chunk_id
  -> answer_question_with_chunks(question, retrieved_chunks)
```

为什么向量检索后还要回实体库取 chunks：

```text
向量库返回候选 chunk_id。
实体库返回权威 chunk 文本和 metadata。
这样不会依赖向量库 metadata 里冗余保存的正文。
```

推荐新增服务：

```text
app/services/vector_store.py
  index_document_chunks(project_id: str, chunks: list[dict]) -> dict
  search_within_paper(paper_version_id: str, query: str, top_k: int = 8) -> list[str]
  search_related_papers(source_paper_id: str, query: str, top_papers: int = 5, chunks_per_paper: int = 3) -> list[dict]
  delete_project_vectors(project_id: str) -> None
```

推荐新增数据库 helper：

```text
list_document_chunks_by_ids(project_id: str, chunk_ids: list[str]) -> list[dict]
```

检索结果顺序规则：

```text
1. 向量检索结果按语义相似度排序。
2. 通过 chunk_ids 回实体库取原文。
3. QA 保留相似度排序。
4. 长文本总结或代码规划可以按 order_index 恢复论文原顺序。
```

## 推荐向量库选择

当前阶段优先选择本地、简单、可持久化的方案：

```text
Chroma
```

推荐第一版：

```text
Chroma persistent local store under data/vector_store
```

原因：

```text
本地运行。
后端重启后仍然持久化。
支持 metadata filter。
不需要额外 Docker 服务。
适合当前单机开发阶段。
```

备选：

```text
FAISS + SQLite metadata
```

选择 FAISS 的原因：

```text
本地相似度搜索快。
适合单机实验。
```

不建议第一版选 FAISS 的原因：

```text
metadata filter、删除、按 project/user 隔离都需要更多自定义代码。
```

生产环境后续可以考虑：

```text
Qdrant, Milvus, Weaviate, pgvector
```

除非当前任务已经包含部署和运维，否则不要一开始就上这些外部服务。

## 多用户隔离

当系统加入用户体系后，每个持久层都需要 `user_id`。

实体库：

```text
projects.user_id
projects.paper_id
projects.paper_version_id
document_chunks.user_id 或通过 projects join 得到 user_id
document_chunks.paper_id
document_chunks.paper_version_id
project_events.user_id 可选，通常通过 projects join 就够
```

向量库 metadata：

```text
user_id
project_id
paper_id
paper_version_id
chunk_id
```

每次向量查询必须过滤：

```text
user_id == current_user_id
project_id == requested_project_id
```

原因：

```text
语义检索如果没有严格过滤，很容易跨用户命中相似论文。
这是严重的数据隔离问题。
```

跨论文发散检索时，过滤条件必须改为：

```text
user_id == current_user_id 或 corpus_scope == public
paper_id != source_paper_id
```

原因：

```text
发散检索要找相关论文，而不是找当前论文的其他版本。
```

## 失败与重试规则

保持简单：

```text
如果实体库保存失败：
  project 标记失败；不要索引 vectors。

如果向量索引失败：
  保留 project/chunks；标记 vector index failed；允许重试。

如果 embedding API 部分失败：
  重试失败 batch；仍失败则只让 vector indexing 失败。

如果 chunking 规则变化：
  删除该 project_id 的 vectors；保存新 chunks；重新索引。
```

原因：

```text
实体库失败说明事实源不完整。
向量库失败只是检索索引缺失或过期，论文和 chunks 仍可恢复。
```

## 实现计划

### 第一期：实体库补强

增加后续向量索引需要的字段：

```text
papers table
paper_versions table
projects.user_id              # 没有 auth 时可以 nullable
projects.paper_id
projects.paper_version_id
projects.file_sha256
document_chunks.content_hash
document_chunks.paper_id
document_chunks.paper_version_id
vector_index_records table
```

增加 helper：

```text
list_document_chunks_by_ids(project_id, chunk_ids)
save_vector_index_records(records)
delete_vector_index_records(project_id)
find_or_create_paper_identity(metadata)
create_paper_version(paper_id, file_sha256, project_id)
```

迁移方式保持简单：

```text
使用 PRAGMA table_info 检查字段是否存在。
缺少 nullable 字段时用 ALTER TABLE 添加。
```

### 第二期：Embedding Client

新增：

```text
app/services/embedding_client.py
```

职责：

```text
读取 EMBEDDING_MODEL
调用 OpenAI embeddings API 或兼容 provider
按 batch 处理 texts
按输入顺序返回 vectors
抛出清晰错误
```

不要把 embedding 调用混进 `llm_paper_analyzer.py`。

### 第三期：Vector Store Service

新增：

```text
app/services/vector_store.py
```

职责：

```text
初始化持久化向量库
按 project_id 删除旧 vectors
批量 upsert chunk vectors
论文内检索使用 paper_version_id/user_id filter
跨论文发散检索使用 user_id/public scope，并排除 source_paper_id
返回 chunk_ids 和 scores
```

推荐路径：

```text
data/vector_store
```

推荐 collection：

```text
paper_chunks
```

### 第四期：接入 Pipeline

在 chunk 保存后接入：

```text
db_chunks = save_chunks()
index_document_chunks(project_id, db_chunks)
```

增加状态：

```text
ProjectStatus.INDEXING_VECTORS
```

整体调用顺序变为：

```text
parse document
chunk document
save chunks to entity DB
index chunks to vector DB
analyze paper
build report
plan code
generate code
validate/repair code
package artifact
```

原因：

```text
后面的论文分析和代码生成可以逐步改成 retrieval-based context，而不是固定取前几个 chunks。
```

### 第五期：QA 改成向量检索

修改 `routes_qa.py`：

```text
chunk_ids = search_within_paper(paper_version_id, question, top_k=8)
chunks = list_document_chunks_by_ids(project_id, chunk_ids)
result = answer_question_with_chunks(question, chunks)
```

兜底策略：

```text
如果向量索引不可用，临时回退到 list_document_chunks(project_id)。
```

兜底必须记录 project event，不要静默发生。

### 第六期：跨论文发散检索

新增 service 函数：

```text
search_related_papers(source_paper_id, query, top_papers=5, chunks_per_paper=3)
```

要求：

```text
必须排除 source_paper_id。
必须按 paper_id 分组。
每个 paper_id 最多返回 chunks_per_paper 个证据 chunks。
返回结果必须包含 paper_id、title、score、reason、chunks。
```

不要把同一个 `paper_id` 的不同版本当成相关论文返回。

### 第七期：Reindex 函数或任务

先加内部函数：

```text
reindex_project(project_id)
  -> chunks = list_document_chunks(project_id)
  -> delete_project_vectors(project_id)
  -> index_document_chunks(project_id, chunks)
```

只有 UI 或管理后台需要时，再加 API endpoint。

## 验收检查

完成向量库集成前，确认：

- 上传后会创建一条 project row。
- 同一篇论文重复上传时，会归入同一个 paper_id，并创建新的 paper_version_id。
- pipeline 会保存 chunks 到 `document_chunks`。
- 向量索引只在 chunks 已经提交到实体库后开始。
- 每条 vector 都有 `project_id`、`paper_id`、`paper_version_id`、`chunk_id`、`order_index`、`embedding_model`。
- 同一个 project 重新处理时不会残留旧 vectors。
- 旧系统行为已被替换：不能再把同一篇论文重复上传当成完全无关的新论文。
- QA 使用 top-k 向量检索结果，而不是把所有 chunks 发送给 LLM。
- 论文内 QA 只检索当前 paper_version_id。
- 跨论文发散检索必须排除当前 paper_id。
- 跨论文发散检索结果必须按 paper_id 分组。
- 返回的 `used_chunks` 必须是真实存在于实体库的 `chunk_id`。
- 向量库失败不会删除实体库 chunks 或原始文件。
- 多用户上线前，向量查询必须带 user/project filter。

## 最小第一版改动范围

低风险第一版只改这些位置：

```text
app/config.py
app/core/models.py
app/core/database.py
app/services/embedding_client.py
app/services/vector_store.py
app/workers/pipeline.py
app/api/routes_qa.py
requirements.txt
```

后端检索跑通前，不需要改前端。

不要用向量库替换实体库。正确设计是两者并存：

```text
SQLite/entity DB:
  事实源，保存 project state、chunks、metadata、events

Vector DB:
  基于 chunk text 的语义检索索引
```
