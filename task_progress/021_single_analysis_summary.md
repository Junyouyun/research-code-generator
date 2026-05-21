# 021 Single Analysis Summary

## 本次目标

减少总结阶段的中间文件，只保留一个 `analysis.json`，并增加最终总结结果。

## 完成内容

- 不再单独写入：
  - `chunk_summaries.json`
  - `agent_dialogue.json`
- `analysis.json` 现在包含：
  - 原有全局分析字段
  - `final_summary`
  - `debug.section_summaries`
  - `debug.agent_dialogue`
- LangGraph 新增 `final_summary` 节点。
- 新增 `build_final_summary`，让 LLM 基于全局分析、章节总结、多 agent 评审生成最终总结。
- `report_generator.py` 改为优先使用 `final_summary` 生成报告。

## 当前边界

- 总结分析步骤没有减少，只是文件保存更集中。
- 代码生成部分暂时不改。
- 旧项目目录中已经存在的历史 JSON 文件不会自动删除。
