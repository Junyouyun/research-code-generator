# 020 LangGraph Analysis Graph

## 本次目标

把 LLM 分析流程接入 LangGraph，让 section 分析、多 agent 交互和全局汇总以图节点方式执行。

## 完成内容

- 在后端依赖中加入 `langgraph`。
- 新增 `llm_analysis_graph.py`，定义分析图：
  - `prepare_sections`
  - `summarize_sections`
  - `agent_dialogue`
  - `global_analysis`
- `analyze_paper_with_llm` 改为调用 LangGraph 图。
- 保持 `pipeline.py` 调用方式不变。
- 保持输出结构不变：`analysis, section_summaries`。
- 增加 LangGraph 节点级进度日志。

## 当前边界

- 只把 LLM 分析链路图化。
- 没有把文档解析、chunk 入库、报告生成、代码生成迁移进 LangGraph。
- 没有启用 LangGraph checkpoint。
- 没有修改数据库结构。

## 下一步建议

- 如果图编排稳定，再考虑把 checkpoint 接到 SQLite。
- 后续可以把每个 agent 的输入输出单独保存，方便前端展示多 agent 推理过程。
