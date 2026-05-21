# Phase 02: Code-Based Chunker

## 1. 一句话目标

基于 `DocumentElement[]`，用代码生成稳定的语义 chunks。

这一阶段不让模型切分。

```text
DocumentElement[] -> Chunk[]
```

## 2. 第一版范围

第一版只做确定性切分：

- 按标题层级组织内容。
- 特殊元素单独成块。
- 普通文本按 token 限制切分。
- 相邻普通 chunk 保留 overlap。
- 输出完整 metadata。

不做：

- 向量化
- 模型判断语义边界
- OCR
- 图片内容理解

## 3. 核心参数

```python
MIN_CHUNK_TOKENS = 100
TARGET_CHUNK_TOKENS = 768
MAX_CHUNK_TOKENS = 1024
OVERLAP_TOKENS = 128
```

第一版如果还没有 tokenizer，可以先用近似 token 计数：

```text
英文：约 4 字符 = 1 token
中文：约 1.5 到 2 字符 = 1 token
```

后续再接 `tiktoken`。

## 4. Chunk 字段

```python
{
    "chunk_id": "doc_project_id_chunk_001",
    "content": "chunk markdown content",
    "metadata": {
        "document_id": "project_id",
        "document_title": "",
        "section_title": "Method",
        "hierarchy_path": "Method > Model",
        "page_start": 3,
        "page_end": 4,
        "element_type": "paragraph",
        "chunk_size_tokens": 768,
        "is_special_element": false,
        "is_cross_page": true,
        "is_split_sentence": false,
        "is_forced_split": false,
        "needs_review": false,
        "source_file_type": "pdf",
        "order_index": 1
    }
}
```

## 5. 切分优先级

切分边界从高到低：

```text
特殊元素边界
-> 标题层级
-> 段落边界
-> 句子边界
-> 逗号边界
-> 强制切分
```

原则：

- 不拆表格。
- 不拆代码块。
- 不拆独立公式。
- 尽量不拆完整句子。
- 强制切分时必须标记 `is_forced_split = true`。

## 6. 特殊元素规则

这些元素默认单独成块：

- `table`
- `formula`
- `code`
- `figure`
- `reference`

特殊元素不参与普通文本 overlap。

如果特殊元素超过 `MAX_CHUNK_TOKENS`：

- 第一版先保持完整。
- 标记 `needs_review = true`。
- 标记 `is_forced_split = false`。

不要为了大小强行破坏表格或代码块。

## 7. 普通文本合并规则

普通元素包括：

- `title`
- `paragraph`
- `list`
- `unknown`

处理流程：

```text
按 order_index 遍历 elements
-> 遇到同一 hierarchy_path 的普通元素，尝试合并
-> 接近 TARGET_CHUNK_TOKENS 时输出一个 chunk
-> 超过 MAX_CHUNK_TOKENS 时按句子边界切分
```

## 8. Overlap 规则

只对相邻普通文本 chunk 做 overlap：

```text
上一块最后 1-2 句
+ 下一块前 1-2 句
约 128 tokens
```

要求：

- overlap 必须是完整句子。
- overlap 不改变原始 `order_index`。
- 特殊元素不做 overlap。

## 9. 句子切分

第一版支持：

```text
. ? !
。？！
```

如果句子过长，再按：

```text
, ;
，；
```

最后才强制按 token 截断。

## 10. Schema 校验

每个 chunk 输出前必须校验：

- `chunk_id` 不为空。
- `content` 不为空。
- `metadata` 字段完整。
- `chunk_size_tokens` 是数字。
- `order_index` 是数字。
- boolean 字段是真正的 bool。

校验失败：

```python
needs_review = true
```

不要直接丢弃内容。

## 11. 输出文件

保存到：

```text
data/parsed/{project_id}/chunks.json
```

## 12. 验收标准

完成这一阶段后，至少满足：

- `elements.json` 可以生成 `chunks.json`。
- 普通 chunk 大小主要落在 100-1024 tokens。
- 特殊元素独立成块。
- chunk 顺序和文档阅读顺序一致。
- 所有 chunk 都带完整 metadata。

