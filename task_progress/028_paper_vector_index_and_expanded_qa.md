# 028 Paper Vector Index And Expanded QA

## 本次目标

为论文上传后的实体库、向量库和问答流程补齐主链路：

- 同一份 PDF 重复上传时能够复用 `paper_id`。
- 每次上传都创建新的 `paper_version_id` 和 `project_id`。
- chunks 入库时携带 `paper_id`、`paper_version_id`、`content_hash`。
- 使用 Qdrant 建立 chunk 向量索引。
- 论文内 QA 从全量 chunks 改为向量 top-k 检索。
- 用户问题命中扩展关键词时，自动跨论文检索并综合回答。
- 支持手动重建项目向量索引。

## 完成内容

### 1. 实体库结构补强

- 新增 `papers` 表，用于表示论文本身。
- 新增 `paper_versions` 表，用于表示某篇论文的某次上传、解析、切分、向量化版本。
- 新增 `vector_index_records` 表，用于记录哪些 chunks 已写入向量库。
- `projects` 增加：
  - `user_id`
  - `paper_id`
  - `paper_version_id`
  - `file_sha256`
- `document_chunks` 增加：
  - `paper_id`
  - `paper_version_id`
  - `content_hash`
- `init_database()` 增加轻量迁移逻辑，旧 SQLite 表缺字段时自动 `ALTER TABLE` 补齐。

### 2. 上传时绑定论文身份

- 上传 PDF 后计算 `file_sha256`。
- 使用 `user_id + file_sha256` 查找或创建 `paper_id`。
- 当前还没有真实用户系统，统一使用 `user_id = "local"`。
- 每次上传都会创建新的 `paper_version_id`。
- 每次上传任务仍然创建新的 `project_id`。

当前身份关系：

```text
paper_id
  表示同一篇论文。

paper_version_id
  表示这篇论文的一次上传/处理版本。

project_id
  表示一次具体处理任务。
```

### 3. chunks 入库补充论文身份

- `save_document_chunks(project_id, chunks)` 内部根据 `project_id` 读取 `paper_id` 和 `paper_version_id`。
- 每个 chunk 根据 `content` 计算 `content_hash`。
- `list_document_chunks()` 返回的 metadata 中包含：
  - `project_id`
  - `paper_id`
  - `paper_version_id`
  - `content_hash`

### 4. Embedding Client

- 新增 `app/services/embedding_client.py`。
- 提供：

```python
embed_texts(texts: list[str]) -> list[list[float]]
get_embedding_model() -> str
```

- 默认 embedding 模型：

```text
text-embedding-3-small
```

- 支持配置：

```text
EMBEDDING_API_KEY
EMBEDDING_BASE_URL
EMBEDDING_MODEL
EMBEDDING_BATCH_SIZE
EMBEDDING_TIMEOUT_SECONDS
```

说明：

- LLM 和 embedding 是两类模型。
- 当前 DeepSeek 可继续作为 LLM 使用。
- DeepSeek 官方 API 当前没有明确提供 embedding 模型。
- embedding 可单独使用 OpenAI-compatible 服务。

### 5. Qdrant 向量库封装

- 新增 `app/services/vector_store.py`。
- 使用 Qdrant 替代原计划的 Chroma。
- 新增依赖：

```text
qdrant-client
```

- 默认本地持久化路径：

```text
data/qdrant
```

- 默认 collection：

```text
paper_chunks
```

- 提供核心函数：

```python
index_document_chunks(project_id: str, chunks: list[dict]) -> dict
search_within_paper(paper_version_id: str, query: str, top_k: int = 8, user_id: str = "local") -> list[dict]
search_related_papers(source_paper_id: str, query: str, top_papers: int = 5, chunks_per_paper: int = 3, user_id: str = "local") -> list[dict]
delete_project_vectors(project_id: str) -> None
reindex_project(project_id: str) -> dict
```

Qdrant point id 不能直接使用 `doc_xxx_chunk_001` 这类业务字符串，所以当前使用：

```python
uuid5(NAMESPACE_URL, chunk_id)
```

生成稳定的 Qdrant `vector_id`，原始 `chunk_id` 保存在 payload 中。

### 6. Pipeline 接入向量索引

- 新增项目状态：

```python
INDEXING_VECTORS = "indexing_vectors"
```

- pipeline 当前顺序：

```text
parse document
  -> chunk document
  -> save chunks to SQLite
  -> index chunks to Qdrant
  -> LLM summary
  -> build report
  -> plan code
  -> generate code
  -> validate code
  -> package artifact
```

- `vector_store` 在 `index_vectors()` 内部导入，避免未安装 `qdrant-client` 时后端启动失败。

### 7. 论文内 QA 改为向量检索

原流程：

```text
question
  -> list_document_chunks(project_id)
  -> 把全部 chunks 给 LLM
```

新流程：

```text
question
  -> get_project(project_id)
  -> 读取 project.paper_version_id
  -> search_within_paper(paper_version_id, question, top_k=8, user_id=project.user_id)
  -> 得到 chunk_ids
  -> list_document_chunks_by_ids(project_id, chunk_ids)
  -> answer_question_with_chunks(question, retrieved_chunks)
```

新增：

```python
list_document_chunks_by_ids(project_id: str, chunk_ids: list[str]) -> list[dict]
```

### 8. 跨论文检索和自动扩展 QA

- 新增 `POST /api/projects/{project_id}/related-papers`，用于调试跨论文检索结果。
- `search_related_papers()` 会排除：

```text
paper_id == source_paper_id
```

不是只排除当前 `project_id` 或当前 `paper_version_id`。

- 新增 `app/services/query_intent.py`。
- `/qa` 接口现在会根据关键词自动判断是否扩展到相关论文。

普通问题：

```text
当前论文向量检索
  -> LLM 回答
```

命中扩展关键词的问题：

```text
当前论文向量检索
  -> 跨论文向量检索
  -> 回 SQLite 补齐相关论文 chunks 正文
  -> LLM 基于当前论文证据 + 相关论文证据综合回答
```

扩展关键词包括：

```text
对比、比较、类似、相关、扩展、发散、其他论文、相关研究、前人工作、相似方法、替代方法、改进方向、SOTA、related work、compare、similar、prior work 等
```

- `QuestionResponse` 增加：

```python
expanded: bool = False
used_related_chunks: list[str] = []
```

### 9. Reindex 能力

- 新增：

```python
reindex_project(project_id: str) -> dict
```

- 新增 API：

```text
POST /api/projects/{project_id}/reindex
```

流程：

```text
读取当前 project 的 document_chunks
  -> 删除旧 Qdrant vectors
  -> 删除旧 vector_index_records
  -> 重新 embedding
  -> 重新 upsert Qdrant
  -> 重新写 vector_index_records
```

## 涉及文件

- `backend/app/core/models.py`
- `backend/app/core/database.py`
- `backend/app/core/storage.py`
- `backend/app/core/schemas.py`
- `backend/app/config.py`
- `backend/app/api/routes_upload.py`
- `backend/app/api/routes_qa.py`
- `backend/app/api/routes_projects.py`
- `backend/app/workers/pipeline.py`
- `backend/app/services/embedding_client.py`
- `backend/app/services/vector_store.py`
- `backend/app/services/query_intent.py`
- `backend/app/services/llm_paper_analyzer.py`
- `backend/requirements.txt`

## 当前边界

- 当前 `paper_id` 第一版只通过 `user_id + file_sha256` 识别同一份 PDF。
- 这能识别完全相同 PDF 的重复上传，但不能识别同一篇论文的不同 PDF 版本。
- 后续更专业的论文身份识别应补充：
  - DOI
  - arXiv ID
  - normalized title + authors
- 当前 `user_id` 固定为 `local`，后续接入真实用户系统后再替换。
- 当前 `/qa` 的跨论文扩展由关键词触发，可能存在误触发或漏触发。
- 当前 Qdrant 默认使用本地 `data/qdrant`，也支持后续通过 `QDRANT_URL` 切换到远程服务。

## 运行前置条件

需要安装新增依赖：

```powershell
python -m pip install -r requirements.txt
```

至少需要配置 embedding：

```env
EMBEDDING_API_KEY=your_embedding_key
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
```

如果 LLM 继续使用 DeepSeek，可以保持：

```env
LLM_API_KEY=your_deepseek_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

## 验证

已做过的轻量验证：

- `python -m compileall` 覆盖本次修改的核心文件。
- 临时 SQLite 验证：
  - 同一 `file_sha256` 复用同一 `paper_id`
  - 每次上传创建不同 `paper_version_id`
  - chunks 入库包含 `paper_id`、`paper_version_id`、`content_hash`
- 后端路由导入验证：
  - `pipeline import ok`
  - `qa route import ok`
  - `related papers api import ok`
  - `smart qa import ok`
  - `reindex route import ok`

尚未做真实端到端验证：

- 当前本机环境曾显示 `qdrant-client missing`。
- 安装 `qdrant-client` 并配置 embedding key 后，需要上传多篇论文再验证：
  - `indexing_vectors`
  - `/qa`
  - `/related-papers`
  - `/reindex`
