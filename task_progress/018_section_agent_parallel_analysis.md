# 018 Section Agent Parallel Analysis

## 目标

提升 LLM 分析 chunks 的速度。

原来是逐 chunk 串行调用模型：

```text
chunk 1 -> chunk 2 -> chunk 3 -> global analysis
```

现在改为按 section 分组，并发调用多个 section agent：

```text
chunks -> section groups -> section agents 并发分析 -> global agent 汇总
```

## 已完成

- 按 `section_title` / `hierarchy_path` 将 chunks 分组。
- 增加 section agent 分析流程。
- 根据 section 标题自动选择 agent 角色：
  - `method_agent`
  - `experiment_agent`
  - `result_agent`
  - `context_agent`
  - `conclusion_agent`
  - `reference_agent`
  - `general_section_agent`
- 使用 `ThreadPoolExecutor` 并发执行 section 分析。
- 保留原来的全局汇总流程，报告和代码生成链路不需要改。
- 增加 `LLM_MAX_WORKERS` 配置，用于控制最大并发数。
- pipeline 接入 section agent 进度日志。

## 改动文件

- `backend/app/services/llm_paper_analyzer.py`
- `backend/app/workers/pipeline.py`
- `backend/app/config.py`
- `backend/.env`

## 配置

```env
LLM_MAX_WORKERS=3
```

含义：最多同时运行 3 个 section agent 调用模型。

如果模型接口限流或网络不稳定，可以调低：

```env
LLM_MAX_WORKERS=2
```

## 验证

- `python -m compileall app` 通过。
- 使用假模型完成最小测试：
  - 2 个 section 并发分析。
  - 最后 1 次 global analysis 汇总。
  - 总共 3 次模型调用，符合预期。

## 当前状态

已完成。

下一步可以考虑：

- 增加 role agents 审查。
- 增加 critic agent。
- 稳定后再迁移到 LangGraph。
