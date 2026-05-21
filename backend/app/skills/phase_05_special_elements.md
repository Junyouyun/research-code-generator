# Phase 05: Special Elements Enhancement

## 1. 一句话目标

增强表格、公式、图片、扫描内容和复杂版面的解析能力。

这一阶段是在基础链路跑通之后再做，不要提前阻塞主流程。

```text
better parser -> better DocumentElement -> better chunks
```

## 2. 第一版范围

优先增强：

- PDF 阅读顺序
- 表格识别
- 图片/图注识别
- 参考文献切分

暂缓：

- 完整 OCR
- 公式 LaTeX 还原
- 多模态图片理解
- 复杂数学排版恢复

## 3. PDF 阅读顺序增强

当前普通文本提取对双栏论文不稳定。

增强目标：

```text
page blocks
-> detect columns
-> sort by reading order
-> merge paragraphs
```

基本策略：

- 单栏：按 `y0` 再按 `x0` 排序。
- 双栏：先左栏从上到下，再右栏从上到下。
- 页眉页脚：根据重复位置和重复文本删除。
- 跨页段落：根据句子是否结束判断是否合并。

## 4. 表格增强

第一版表格策略：

- 能识别就标记为 `table`。
- 不能识别就保留原文，标记 `unknown` 和 `needs_review`。

增强方向：

- PDF 可尝试使用文本块坐标判断表格区域。
- DOCX 直接读取 table。
- Markdown 直接识别 Markdown table。
- HTML 直接读取 table DOM。
- Excel/CSV 天然作为 table 处理。

表格默认单独成块。

## 5. 公式增强

第一版只做保守处理：

- 行内公式保留在段落里。
- 独立公式如果能识别，单独成块。
- 识别不了就保留原始文本。

不要第一版就追求 LaTeX 还原。

后续可选：

- Mathpix 类 OCR。
- LaTeX 源码解析。
- 多模态模型识别公式图片。

## 6. 图片和图表增强

第一版目标不是理解图片，而是不要丢图。

处理方式：

```text
[图片] Figure 1: xxx
```

metadata 里保留：

- 页码
- bbox
- 图题
- 图注
- 图片保存路径

后续再用多模态模型理解图片内容。

## 7. 参考文献增强

参考文献应该每条独立成块。

基本规则：

- 识别 `References` 标题后的内容。
- 按编号 `[1]`、`1.` 或换行模式拆分。
- 保留完整引用文本。

识别不准时：

```python
needs_review = true
```

## 8. OCR 增强

OCR 只在必要时启用。

触发条件：

- PDF 提取文本过少。
- 页面主要是图片。
- 用户上传图片。

第一版不实现 OCR，只预留接口：

```python
ocr_page(image_path) -> DocumentElement[]
```

## 9. 质量标记

特殊元素增强后，必须给出质量标记：

```python
confidence = 0.0 - 1.0
needs_review = true / false
```

低置信度内容不丢弃，只标记。

## 10. 不做过度设计

这一阶段很容易变复杂。

第一原则：

```text
先不丢内容，再提高结构质量。
```

不要为了识别一个元素，引入过重依赖或复杂流程。

## 11. 验收标准

完成这一阶段后，至少满足：

- 双栏 PDF 阅读顺序明显改善。
- 表格不会被普通段落逻辑随意拆开。
- 图题和图注可以作为 figure 元素保存。
- 参考文献可以拆成独立 reference 元素。
- 低置信度内容有 `needs_review` 标记。

