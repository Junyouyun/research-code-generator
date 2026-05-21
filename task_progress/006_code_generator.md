# 任务 006：代码生成

## 用户要求

在代码规划完成后，实现 `code_generator.py`，让系统根据 `code_plan` 真正生成代码项目文件。

## 本次目标

- 根据 `code_plan["files"]` 生成对应文件。
- 默认生成可运行的 `main.py`。
- 生成 `README.md` 和 `requirements.txt`。
- 为 `data.py`、`model.py`、`train.py`、`evaluate.py` 等模块生成简单占位实现。
- 保证第一版生成代码可以编译和运行。

## 当前进度

- 状态：已完成
- 已完成：
  - 创建任务记录文件。
  - 实现 `code_generator.py` 按规划生成文件。
  - 修复 `code_planner.py` 和 `code_runner.py` 中的乱码残留。
  - 验证生成的 `main.py` 可以运行。
- 待完成：
  - 后续让代码生成接入 LLM，基于论文方法生成更具体实现。
  - 后续增强 `code_runner.py`，检查所有生成的 Python 文件。
