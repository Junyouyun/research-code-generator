# 011 LLM Analysis Pipeline

## 目标

接通 OpenAI-compatible 模型接口，让后端基于更细粒度的论文文本 chunk 生成局部总结，再汇总成报告和代码生成所需的结构化分析。

## 进度

- 已新增论文 chunk 切割服务。
- 已新增模型客户端。
- 已新增基于 chunk summary 的模型分析器。
- 已把 pipeline 的分析阶段改为：chunk -> chunk summary -> global analysis。
- 已保存 `chunks.json`、`chunk_summaries.json`、`analysis.json` 三类中间产物。

## 配置

运行后端前需要设置：

```powershell
$env:LLM_API_KEY="你的模型 API Key"
$env:LLM_BASE_URL="https://api.openai.com/v1"
$env:LLM_MODEL="gpt-4o-mini"
```

如果使用 DeepSeek、通义千问、硅基流动等 OpenAI-compatible 服务，把 `LLM_BASE_URL` 和 `LLM_MODEL` 改成对应服务的值。
