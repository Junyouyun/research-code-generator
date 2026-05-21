# Phase 04: LLM Summary And Analysis

## 1. 一句话目标

模型不负责切分，只基于已经切好的 chunks 做总结、问答和结构化分析。

```text
document_chunks -> chunk summaries -> global analysis
```

## 2. 第一版范围

第一版做：

- 对每个 chunk 生成局部总结。
- 基于局部总结生成全局论文分析。
- 输出兼容现有报告和代码生成的 `analysis.json`。

暂不做：

- 多轮 agent
- 向量检索问答
- 自动运行生成代码
- 复杂引用追踪

## 3. 输入来源

模型输入应该来自数据库或 `chunks.json`。

推荐顺序：

```text
优先读数据库 document_chunks
数据库没有时读 chunks.json
```

不要再直接读 `full_text`。

## 4. Chunk 总结输出

每个 chunk 输出：

```python
{
    "chunk_id": "doc_project_id_chunk_001",
    "summary": "这一块的简要总结",
    "key_points": [],
    "methods": [],
    "experiments": [],
    "code_hints": [],
    "open_questions": []
}
```

要求：

- 只基于当前 chunk 内容。
- 不知道就留空。
- 不编造论文中没有的信息。

## 5. 全局分析输出

全局分析继续兼容当前项目：

```python
{
    "title": "",
    "abstract": "",
    "research_problem": "",
    "main_contribution": [],
    "method_summary": "",
    "experiment_summary": "",
    "reproducible_parts": [],
    "required_inputs": [],
    "possible_code_modules": [],
    "source": "",
    "analysis_source": "llm"
}
```

这样后面的：

- report generator
- code planner
- code generator

可以先不大改。

## 6. 调用策略

第一版采用简单串行：

```text
for chunk in chunks:
    summarize chunk

global_analysis = summarize all chunk summaries
```

后续再考虑：

- 并发调用
- 失败重试
- 成本控制
- 分层 map-reduce 总结

## 7. Prompt 原则

Prompt 必须明确：

- 只基于输入内容。
- 不要编造。
- 输出 JSON。
- 字段缺失时用空字符串或空数组。

不要让模型决定 chunk 边界。

## 8. JSON 解析

模型输出必须经过解析和校验。

处理顺序：

```text
去掉 ```json 包裹
-> json.loads
-> 字段补齐
-> 类型归一化
-> 保存
```

解析失败时：

- 标记项目失败。
- 错误信息写入数据库。
- 不静默生成空报告。

## 9. 中间产物

保存：

```text
chunk_summaries.json
analysis.json
```

后续如果入库，再加：

```text
chunk_summaries table
```

第一版先保存 JSON 即可。

## 10. 成本控制

第一版先限制：

- 单个 chunk 不超过 1024 tokens。
- chunk summary 尽量短。
- 全局总结只输入 chunk summaries，不输入全文。

这样可以避免长论文直接爆上下文。

## 11. 验收标准

完成这一阶段后，至少满足：

- 模型基于 chunks 生成 `chunk_summaries.json`。
- 模型基于 chunk summaries 生成 `analysis.json`。
- `analysis.json` 可以继续驱动报告生成。
- `analysis.json` 可以继续驱动代码规划。
- 未配置模型 key 时错误信息明确。

