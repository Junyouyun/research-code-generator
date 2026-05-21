# 022 Minimal Runnable Code Output

## 本次目标

减少代码产物数量，让生成结果更像一个可以直接配置环境运行的小工具，而不是一堆松散文件。

## 完成内容

- 代码计划固定为少量文件：
  - `README.md`
  - `requirements.txt`
  - `main.py`
  - `config.json`
  - `.env.example`
- `main.py` 变成唯一运行入口。
- `config.json` 保存运行参数：
  - `input_path`
  - `output_dir`
  - `random_seed`
  - `code_profile`
- `.env.example` 提供环境变量示例。
- `README.md` 增加环境配置和运行命令。
- 根据论文分析选择代码类型：
  - `analysis_tool`
  - `data_pipeline`
  - `algorithm_scaffold`
- 不再根据 `possible_code_modules` 自动生成很多 Python 文件。

## 当前边界

- 仍然保留 `code_plan.json`，用于调试代码生成依据。
- 代码默认可运行，但不会伪造论文中没有给出的完整算法细节。
- 如果论文缺少数据或算法细节，生成的是保守的分析工具或算法骨架。

## 验证

- `python -m compileall app` 通过。
- smoke test 生成固定 5 个文件。
- 生成的 `main.py --config config.json` 可运行并输出 `result.json`。
