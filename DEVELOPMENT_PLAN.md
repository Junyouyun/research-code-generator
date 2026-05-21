# 论文报告与代码生成项目开发规划

## 1. 项目目标

本项目用于支持用户上传论文 PDF，系统自动解析论文内容，生成研究报告，并基于论文方法生成一份可运行的代码项目。

核心链路：

```text
上传论文 -> 解析论文 -> 分析论文 -> 生成报告 -> 生成代码 -> 检查代码 -> 打包下载
```

第一版目标是先跑通完整流程，不追求复杂架构。

## 2. 技术路线

- 后端：Python + FastAPI
- 前端：Next.js + React
- 数据库：SQLite
- 文件存储：本地目录
- 后台任务：FastAPI BackgroundTasks
- PDF 解析：PyMuPDF 或 pdfplumber
- LLM 调用：统一封装到 `llm/client.py`

第一版不引入微服务、分布式队列、向量数据库和复杂沙箱。

## 3. 项目结构

```text
research_code/
  backend/
    app/
      main.py
      config.py
      api/
      core/
      services/
      llm/
      workers/
      utils/
    tests/
    requirements.txt

  frontend/
    app/
    components/
    lib/
    package.json

  data/
    uploads/
    parsed/
    generated/
    artifacts/
    db.sqlite3

  generated_projects/
```

## 4. 后端模块职责

### `backend/app/main.py`

FastAPI 应用入口，负责创建应用和注册接口路由。

### `backend/app/config.py`

集中管理项目配置，包括上传目录、解析目录、生成目录、数据库路径、模型名称等。

### `backend/app/api/`

接口层，只负责接收请求、调用服务、返回结果。

- `routes_upload.py`：论文上传，创建项目，触发后台流水线。
- `routes_projects.py`：查询项目状态、当前步骤和进度。
- `routes_reports.py`：获取报告内容。
- `routes_code.py`：获取生成代码文件列表、查看代码、下载压缩包。

### `backend/app/core/`

项目核心基础设施。

- `models.py`：项目、报告、代码产物等核心数据结构。
- `schemas.py`：API 输入输出结构。
- `storage.py`：统一生成和管理文件路径。
- `database.py`：SQLite 初始化和数据访问入口。

### `backend/app/services/`

业务服务层。

- `paper_parser.py`：把 PDF 解析成结构化文本。
- `paper_analyzer.py`：从论文中提取研究问题、方法、实验和可复现点。
- `report_generator.py`：生成 Markdown 研究报告。
- `code_planner.py`：规划需要生成哪些代码文件。
- `code_generator.py`：根据规划生成代码项目。
- `code_runner.py`：执行语法检查和最小运行测试。
- `artifact_builder.py`：打包报告和代码。

### `backend/app/llm/`

LLM 调用层。

- `client.py`：封装模型调用。
- `prompts.py`：集中管理 prompt 模板。

业务代码不直接依赖具体模型 SDK，方便后续切换模型。

### `backend/app/workers/pipeline.py`

串联完整处理流程：

```text
保存上传文件
解析 PDF
分析论文
生成报告
规划代码
生成代码
检查代码
打包产物
更新状态
```

## 5. 前端模块职责

### `frontend/app/page.tsx`

首页即上传页，用户上传论文后进入项目详情页。

### `frontend/app/projects/[id]/page.tsx`

项目详情页，展示处理进度、报告、生成代码和下载入口。

### `frontend/components/UploadPanel.tsx`

论文上传组件。

### `frontend/components/ProjectStatus.tsx`

展示项目当前处理阶段和进度。

### `frontend/components/ReportViewer.tsx`

展示 Markdown 报告。

### `frontend/components/CodeArtifactViewer.tsx`

展示生成代码文件列表、文件内容和运行结果。

### `frontend/lib/api.ts`

统一封装前端请求后端 API 的逻辑。

## 6. 数据目录设计

```text
data/uploads/{project_id}/paper.pdf
data/parsed/{project_id}/paper.json
data/generated/{project_id}/report.md
data/generated/{project_id}/code/
data/artifacts/{project_id}/result.zip
```

第一版使用本地文件系统，路径由 `core/storage.py` 统一管理。

## 7. 项目状态

```text
uploaded
parsing
analyzing
generating_report
planning_code
generating_code
checking_code
packaging
completed
failed
```

前端根据状态展示进度。

## 8. 第一版 MVP

第一版只做这些：

- 上传 PDF。
- 解析正文文本。
- 生成结构化论文分析结果。
- 生成 Markdown 报告。
- 生成 Python 代码项目。
- 执行基础语法检查。
- 打包报告和代码。
- 前端展示状态、报告和代码文件。

暂时不做：

- 多用户权限。
- Docker 沙箱。
- 在线代码编辑器。
- 多模型路由。
- 向量数据库。
- 复杂 OCR。

## 9. 开发顺序

1. 创建后端 FastAPI 基础结构。
2. 实现本地文件存储。
3. 实现项目状态数据结构。
4. 实现 PDF 解析服务。
5. 实现处理流水线。
6. 接入 LLM 分析论文。
7. 生成 Markdown 报告。
8. 生成代码项目。
9. 做代码基础检查。
10. 创建前端上传页和项目详情页。
11. 实现产物下载。
12. 做一次端到端验证。

## 10. 核心原则

项目的关键不是堆很多 Agent，而是稳定地产生三个中间结果：

```text
论文结构化内容 -> 论文理解结果 -> 报告和代码
```

只要中间结果清晰，后续增加 RAG、多 Agent、代码修复和更复杂解析能力都可以自然扩展。
