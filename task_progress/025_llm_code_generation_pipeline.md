# 025 LLM Code Generation Pipeline

## 本次目标

把代码生成从“固定模板”改成“基于论文分析和 chunks 的 LLM 代码项目生成”。

## 完成内容

- 新增 `llm_code_generator.py`
  - 先生成 `code_spec`
  - 再按 `code_spec` 逐文件生成代码
  - 默认生成 Docker 运行环境
  - Python 文件会做语法解析，失败后自动让模型修复一次
- 改造 `code_planner.py`
  - 现在返回 LLM 生成的 `code_spec`
  - 输入支持 `analysis + chunks`
- 改造 `code_generator.py`
  - 不再使用固定 `main.py` 模板
  - 改为按 `code_spec` 调用 LLM 生成文件内容
- 改造 `pipeline.py`
  - 规划代码时传入数据库 chunks
  - 生成代码时传入 `analysis + chunks`
  - 保存 `code_spec.json`
  - 保留 `code_plan.json` 兼容旧查看方式

## 当前边界

- 当前只做静态语法检查，不自动 docker build / docker run。
- 生成质量取决于论文 chunks 中是否有足够算法、公式、参数和实验细节。
- 如果论文缺少关键细节，代码会在 assumptions 和 missing_details 中记录默认假设。

## 验证

- `python -m compileall app` 通过。

