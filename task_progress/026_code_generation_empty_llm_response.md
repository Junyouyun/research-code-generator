# 026 Code Generation Empty LLM Response

## 本次目标

修复代码生成阶段偶发 `模型接口返回为空，缺少 message.content` 的问题。

## 完成内容

- 压缩单文件代码生成上下文：
  - `MAX_FILE_CHUNKS` 从 8 降到 4
  - `MAX_CHUNK_CHARS` 从 1800 降到 1200
- 单文件生成失败后自动使用更短上下文重试一次。
- 代码生成失败时会带上具体文件名，例如 `生成 src/xxx.py 失败`。
- LLM 空响应错误增加诊断信息：
  - `finish_reason`
  - `refusal`
- 重写 `llm/client.py` 为正常 UTF-8 中文错误信息。

## 当前状态

这次没有降低“真实代码生成”的目标，只是把单次请求拆得更稳，减少模型空响应和截断概率。

## 验证

- `python -m compileall app` 通过。

