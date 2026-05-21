# 027 Parallel Code Generation

## 本次目标

修复代码生成阶段单文件语法错误导致任务失败的问题，并提升多文件代码生成速度。

## 完成内容

- 新增 `CODE_GEN_MAX_WORKERS` 配置，默认 3。
- 代码文件生成改为并发执行：
  - 本地模板文件仍然直接生成
  - LLM 代码文件使用线程池并发生成
- Python 文件增加多轮语法修复：
  - 首次生成后执行 `ast.parse`
  - 失败后最多修复 2 次
  - 仍失败时生成可运行 fallback 文件，避免整个任务失败
- 整理 `llm_code_generator.py`，把乱码提示词改成稳定英文提示，减少编码问题。

## 当前边界

- fallback 文件能保证项目继续打包，但该文件原始实现需要人工复查。
- 并发数不建议太高，DeepSeek 同时请求过多可能空响应或限流。
- 后续可以增加 Docker build / smoke test，让代码运行错误也能自动回传修复。

## 验证

- `python -m compileall app` 通过。

