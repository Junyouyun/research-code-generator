# 015 Special Elements Enhancement

## 目标

增强表格、公式、图片、参考文献和复杂 PDF 阅读顺序的解析能力。

## 进度

- 已增强 PDF block 排序，加入简单双栏阅读顺序判断。
- 已加入 PDF 页眉页脚重复文本过滤。
- 已识别 PDF 图片块为 `figure`。
- 已识别疑似表格为 `table`。
- 已识别疑似独立公式为 `formula`。
- 已增强 `References` 后参考文献识别。
- 已增强 Markdown 图片、公式、表格、代码块识别。
- 已增强 DOCX 表格顺序处理。
- 已修正 chunker 的中英文句子和逗号切分正则。

## 当前范围

- 暂不做 OCR。
- 暂不做图片内容理解。
- 暂不做公式 LaTeX 还原。
- 暂不做复杂表格结构恢复。
- 低置信度图片块会标记 `needs_review`。
