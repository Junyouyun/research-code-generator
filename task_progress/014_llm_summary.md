# 014 LLM Summary And Analysis

## 目标

让 LLM 基于已经切好的 chunks 做局部总结、全局结构化分析，并预留基于 chunks 的问答能力。

## 进度

- 已重写 `llm_paper_analyzer.py`。
- 已保留 `analyze_paper_with_llm(parsed_paper, chunks)`，pipeline 不需要大改。
- 已新增公开函数：
  - `summarize_chunk`
  - `build_global_analysis`
  - `answer_question_with_chunks`
- 已把 prompt 改成正常中文。
- 已增强 JSON 解析和字段归一化。

## 当前范围

- LLM 不负责切分。
- LLM 输入来自已经生成并从数据库读取的 chunks。
- 暂不做向量检索。
- 暂不做问答 API。
- 暂不做并发调用。
