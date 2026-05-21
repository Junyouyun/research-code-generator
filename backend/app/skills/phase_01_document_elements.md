# Phase 01: Unified Document Elements

## 1. 一句话目标

把不同类型的文档先解析成统一的 `DocumentElement` 列表。

这一阶段不负责切 chunk，不调用模型，只做一件事：

```text
input file -> loader -> DocumentElement[]
```

## 2. 第一版范围

第一版先支持：

- PDF
- Markdown
- TXT
- DOCX

暂不做：

- OCR
- 图片内容理解
- 公式还原
- 向量数据库
- 模型总结

## 3. 为什么要先做这一层

不同文档的原始结构完全不同：

- PDF 有页码、坐标、文本块。
- Markdown 有标题、代码块、表格。
- TXT 几乎没有结构。
- DOCX 有段落、标题、表格。

如果直接对每种文件写 chunk 逻辑，后面会越来越乱。

所以先统一成：

```python
DocumentElement
```

后面的 chunker 只处理 `DocumentElement[]`，不关心文件来源。

## 4. DocumentElement 字段

```python
{
    "element_id": "element_000001",
    "document_id": "project_id",
    "source_file_type": "pdf",
    "type": "title",
    "text": "Introduction",
    "markdown": "## Introduction",
    "page_start": 1,
    "page_end": 1,
    "bbox": [0, 0, 0, 0],
    "section_title": "Introduction",
    "hierarchy_path": "Introduction",
    "order_index": 1,
    "confidence": 1.0,
    "needs_review": false
}
```

## 5. 字段说明

最小必须字段：

- `element_id`: 元素唯一 ID。
- `document_id`: 项目或文档 ID。
- `source_file_type`: 文件类型。
- `type`: 元素类型。
- `text`: 纯文本内容。
- `markdown`: 保留格式后的内容。
- `order_index`: 文档阅读顺序。

可为空但必须存在：

- `page_start`
- `page_end`
- `bbox`
- `section_title`
- `hierarchy_path`

质量字段：

- `confidence`: 解析置信度。
- `needs_review`: 是否需要后续检查。

## 6. 元素类型

第一版支持：

```text
title
paragraph
table
formula
code
figure
list
reference
unknown
```

识别不了的内容不要丢弃，统一标记为：

```python
type = "unknown"
needs_review = true
```

## 7. Loader 责任

每个 loader 只负责一件事：

```text
文件 -> DocumentElement[]
```

不要在 loader 里做：

- chunk 切分
- 模型总结
- 代码生成
- 入库

## 8. PDF Loader 第一版

PDF 第一版用 PyMuPDF：

```text
page.get_text("blocks") or page.get_text("dict")
```

最低要求：

- 保留页码。
- 保留文本块顺序。
- 保留 bbox。
- 尽量识别标题和段落。
- 图片、公式、表格识别不了时标记为 `unknown`。

## 9. Markdown Loader 第一版

Markdown 结构最清楚，优先做好。

需要识别：

- `# / ## / ###` 标题
- 普通段落
- 列表
- 代码块
- Markdown 表格

Markdown 的 `hierarchy_path` 应该最完整。

## 10. TXT Loader 第一版

TXT 缺少结构，所以保持简单：

- 空行分段落。
- 短行或编号行可以猜测为标题。
- 其他内容全部作为 paragraph。

置信度可以低一些。

## 11. DOCX Loader 第一版

DOCX 需要读取：

- heading 样式
- paragraph
- table
- list

第一版可以先只处理标题、段落、表格。

## 12. 输出文件

解析完成后保存：

```text
data/parsed/{project_id}/elements.json
```

格式：

```json
[
  {
    "element_id": "element_000001",
    "type": "title",
    "text": "Introduction"
  }
]
```

## 13. 验收标准

完成这一阶段后，至少满足：

- 上传 PDF 可以生成 `elements.json`。
- 上传 Markdown 可以生成 `elements.json`。
- 每个 element 有稳定的 `order_index`。
- 不同文件类型输出同一种结构。
- 不丢弃无法识别的内容。

