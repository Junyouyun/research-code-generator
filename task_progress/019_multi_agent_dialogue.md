# 019 Multi Agent Dialogue

## 目标

在 section agent 并发分析之后，增加多 agent 多轮交互，让系统不只是更快，也能更稳地判断：

- 论文方法是否清楚。
- 实验或案例是否充分。
- 哪些内容适合生成代码。
- 哪些地方信息不足，不能强行复现。

## 已完成

- 增加 4 个评审角色：
  - `method_agent`
  - `experiment_agent`
  - `code_agent`
  - `critic_agent`
- 增加固定多轮对话流程。
- 每一轮中 4 个评审 agent 并发执行。
- 每个 agent 会读取上一轮其他 agent 的观点，并修正自己的判断。
- 增加 `planner_agent`，用于综合多轮对话，输出最终代码策略和复现风险。
- `global analysis` 会结合 section summaries 和 planner review 生成最终分析。
- pipeline 会保存 `agent_dialogue.json`。
- 报告中增加“多 Agent 评审结论”。
- 代码计划中增加：
  - `code_generation_strategy`
  - `reproducibility_risk`

## 改动文件

- `backend/app/services/llm_paper_analyzer.py`
- `backend/app/workers/pipeline.py`
- `backend/app/config.py`
- `backend/.env`
- `backend/app/services/report_generator.py`
- `backend/app/services/code_planner.py`
- `backend/app/services/code_generator.py`

## 配置

```env
AGENT_DIALOGUE_ROUNDS=2
AGENT_MAX_WORKERS=4
```

含义：

- `AGENT_DIALOGUE_ROUNDS`：多 agent 交互轮数。
- `AGENT_MAX_WORKERS`：每轮最多同时运行多少个评审 agent。

## 输出产物

```text
data/parsed/{project_id}/agent_dialogue.json
```

同时 `analysis.json` 中也会包含：

```text
agent_dialogue
code_generation_strategy
reproducibility_risk
```

## 验证

- `python -m compileall app` 通过。
- 使用假模型完成最小链路测试：
  - 2 个 section agent 分析。
  - 2 轮多 agent 交互。
  - 每轮 4 个 role agent。
  - 1 次 planner 汇总。
  - 1 次 global analysis。
  - 总计 12 次模拟模型调用。

## 当前状态

已完成。

后续可以考虑迁移到 LangGraph，把每个 agent 和 planner 做成可恢复的图节点。
