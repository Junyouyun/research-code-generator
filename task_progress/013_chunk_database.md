# 013 Chunk Database

## 目标

把生成好的 chunks 保存进 SQLite，让后续总结、问答、检索都可以从数据库读取。

## 进度

- 已新增 `document_chunks` 表。
- 已新增 chunk 数据库接口：
  - `create_chunks_table`
  - `save_document_chunks`
  - `list_document_chunks`
  - `delete_document_chunks`
- 已在 pipeline 中保存 `chunks.json` 后写入 SQLite。
- 已让 LLM 总结阶段从 SQLite 读取 chunks。

## 当前范围

- 暂不做 embedding。
- 暂不做向量数据库。
- 暂不做问答接口。
- `chunks.json` 继续保留，用于调试和人工检查。
