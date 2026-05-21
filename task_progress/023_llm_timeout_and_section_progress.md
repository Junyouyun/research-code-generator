# 023 LLM 超时与 section 进度

## 本次完成

- 给模型请求增加超时控制，默认 90 秒。
- `section agent` 增加开始、失败、完成日志，便于看出到底是排队、处理中还是超时。
- 下调单个 section 的输入上限，减少单次请求过大导致的长时间阻塞。
- 过滤少量明显噪声 section，例如纯公式、参考文献、页眉页脚授权信息、通讯作者信息。

## 改动文件

- `backend/app/config.py`
- `backend/app/llm/client.py`
- `backend/app/services/llm_paper_analyzer.py`

## 目的

- 减少 `section agent 完成 1/N` 长时间不动的情况。
- 让前端和终端能更清楚看到分析过程卡在哪一步。
