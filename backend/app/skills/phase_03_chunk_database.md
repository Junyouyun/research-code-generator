# Phase 03: Chunk Database

## 1. 一句话目标

把生成好的 chunks 保存进 SQLite，后续总结、问答、检索都从数据库读取。

```text
chunks.json -> document_chunks table
```

## 2. 第一版范围

第一版只做结构化入库：

- 保存 chunk 内容。
- 保存 metadata。
- 按 `project_id` 查询 chunks。
- 按 `order_index` 返回阅读顺序。

暂不做：

- embedding
- 向量数据库
- 混合检索
- 问答历史

## 3. 表结构

```sql
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    content TEXT NOT NULL,
    document_title TEXT,
    section_title TEXT,
    hierarchy_path TEXT,
    page_start INTEGER,
    page_end INTEGER,
    element_type TEXT NOT NULL,
    chunk_size_tokens INTEGER NOT NULL,
    is_special_element INTEGER NOT NULL,
    is_cross_page INTEGER NOT NULL,
    is_split_sentence INTEGER NOT NULL,
    is_forced_split INTEGER NOT NULL,
    needs_review INTEGER NOT NULL,
    source_file_type TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
```

## 4. 最小数据库接口

第一版需要这些函数：

```python
create_chunks_table()
save_document_chunks(project_id: str, chunks: list[dict]) -> None
list_document_chunks(project_id: str) -> list[dict]
delete_document_chunks(project_id: str) -> None
```

## 5. 入库规则

保存前：

- 先删除同一个 `project_id` 下的旧 chunks。
- 再插入新的 chunks。
- 插入失败时让 pipeline 失败，不做静默忽略。

这样方便重复上传和调试。

## 6. 查询规则

默认查询：

```sql
SELECT * FROM document_chunks
WHERE project_id = ?
ORDER BY order_index ASC;
```

不要默认按 `chunk_id` 排序，因为字符串排序不一定等于阅读顺序。

## 7. Boolean 存储

SQLite 没有真正的 boolean。

统一保存为：

```text
true  -> 1
false -> 0
```

读取时转回 Python bool。

## 8. 和文件缓存的关系

第一版同时保留：

```text
chunks.json
document_chunks table
```

原因：

- JSON 方便人工调试。
- SQLite 方便后续接口查询。

后续稳定后，可以让数据库成为主数据源。

## 9. Pipeline 接入点

推荐接入位置：

```text
parse file
-> build elements
-> build chunks
-> save chunks.json
-> save chunks to database
-> llm summarize chunks
```

也就是说，模型总结之前必须完成 chunks 入库。

## 10. 后续扩展表

后续做向量检索时再加：

```sql
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding BLOB NOT NULL,
    created_at TEXT NOT NULL
);
```

第一版不要做，避免过早复杂化。

## 11. 验收标准

完成这一阶段后，至少满足：

- pipeline 能把 chunks 写入 SQLite。
- 能按 `project_id` 查询全部 chunks。
- 返回顺序与文档阅读顺序一致。
- 重新处理同一项目时不会留下旧 chunks。
- JSON 文件和数据库内容数量一致。

