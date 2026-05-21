# 任务 008：后端端到端验证

## 用户要求

安装依赖并完成一次后端端到端验证。

## 本次目标

- 安装后端依赖。
- 启动 FastAPI 后端服务。
- 准备测试 PDF。
- 调用上传接口。
- 查询项目状态。
- 验证生成 `paper.json`、`analysis.json`、`report.md`、`code_plan.json`、`code/` 和 `result.zip`。
- 验证报告、代码和压缩包接口可用。

## 当前进度

- 状态：已完成
- 已完成：
  - 创建任务记录文件。
  - 确认当前项目内没有可直接使用的 PDF。
  - 安装后端依赖。
  - 验证 `uvicorn app.main:app` 可以正常启动。
  - 使用 PyMuPDF 生成测试 PDF。
  - 使用 FastAPI `TestClient` 调用上传接口完成端到端验证。
  - 验证报告、代码文件和 zip 下载接口可用。
- 待完成：
  - 后续处理后台服务启动方式。
  - 后续接入前端页面。

## 验证结果

- 测试项目 ID：`b1d1982c09f341c69298255bda13d025`
- 项目最终状态：`completed`
- 生成产物：
  - `paper.json`
  - `analysis.json`
  - `report.md`
  - `code_plan.json`
  - `code/`
  - `result.zip`
- 代码接口返回文件：
  - `data.py`
  - `evaluate.py`
  - `main.py`
  - `model.py`
  - `README.md`
  - `requirements.txt`
  - `train.py`

## 说明

前台启动后端服务验证通过。后台 `Start-Process` 方式在当前 PowerShell 环境中会很快退出，所以本次端到端接口验证使用 `TestClient` 在进程内完成。
