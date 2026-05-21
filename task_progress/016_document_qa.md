# 016 Document QA API

## 目标

暴露基于文档 chunks 的问答接口，让用户可以针对已上传文档提问。

## 进度

- 已新增 `POST /api/projects/{project_id}/qa`。
- 已新增请求模型 `QuestionRequest`。
- 已新增响应模型 `QuestionResponse`。
- 已从 SQLite 的 `document_chunks` 表读取 chunks。
- 已调用 `answer_question_with_chunks` 生成回答。

## 当前范围

- 暂不做向量检索。
- 暂不做前端问答界面。
- 第一版会把该项目全部 chunks 交给 LLM。
