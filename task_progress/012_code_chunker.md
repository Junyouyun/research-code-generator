# 012 Code-Based Chunker

## 目标

基于 `DocumentElement[]`，用代码生成稳定的语义 chunks，不让模型决定切分边界。

## 进度

- 已新增 `document_chunker.py`。
- 已支持特殊元素单独成块。
- 已支持普通文本按标题层级、token 近似计数和句子边界切分。
- 已支持普通 chunk 的 overlap。
- 已输出完整 metadata，并保留兼容字段 `title/page_start/page_end`。
- 已把 pipeline 从旧 `paper_chunker` 切换到新 `document_chunker`。

## 当前限制

- token 计数是近似值，后续可以替换成 `tiktoken`。
- 句子切分是规则实现，暂不做模型语义判断。
- 特殊元素过长时不强拆，只标记 `needs_review`。
