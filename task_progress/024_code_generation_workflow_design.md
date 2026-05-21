# 024 Code Generation Workflow Design

## 本次目标

为“论文驱动的真实代码生成”新增流程设计说明，替代当前只生成保守模板代码的方向。

## 完成内容

- 新增目录：`code_generation_workflow`
- 新增流程说明：`code_generation_workflow/README.md`
- 新增 Mermaid 流程图：`code_generation_workflow/flow.mmd`
- 明确新代码生成链路：
  - `analysis + chunks`
  - `code_requirements`
  - `code_spec`
  - 逐文件生成
  - 静态检查
  - Docker 环境
  - 打包下载

## 当前状态

本次只完成设计文档和流程图，没有修改后端代码生成逻辑。

下一步可以基于该流程改造：

- `code_planner.py`
- `code_generator.py`
- `pipeline.py`
- 新增 `llm_code_generator.py`

