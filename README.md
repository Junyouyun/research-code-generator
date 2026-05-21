# Research Code Generator

Research Code Generator 是一个面向论文复现辅助的 Web 项目。用户上传论文 PDF 后，系统会解析论文、总结方法与实验信息、建立论文向量索引，并生成一个可下载的研究代码工程压缩包。

项目目标不是直接复现论文的完整实验结果，而是先生成一个结构清晰、接口一致、可以运行 smoke experiment 的代码工程。后续用户可以在这个基础上补充真实数据、完整超参数和正式实验流程。

## 当前能力

- 上传 PDF 论文并创建项目。
- 解析论文文本、章节、chunks。
- 使用 LLM 生成论文总结、报告和代码生成计划。
- 将论文 chunks 保存到实体数据库。
- 使用 embedding 模型和 Qdrant 建立向量索引。
- 支持论文内问答和跨论文扩展检索。
- 生成可运行的研究代码工程。
- 生成代码前先构建 `experiment_spec`，明确论文实验类型、状态、动作、奖励、数据和 smoke validation。
- 对已支持的论文类型套用固定实验框架，减少多文件接口漂移。
- 在临时 venv 中安装依赖并运行 smoke validation，不污染本机 Python 环境。
- 对生成代码做实验级校验，确认代码不只是 `returncode=0`，而是真的跑过环境、agent 和训练循环。

## 技术栈

后端：

- FastAPI
- SQLite
- LangGraph
- OpenAI-compatible LLM API
- OpenAI-compatible Embedding API
- Qdrant
- PyMuPDF

前端：

- Next.js
- React
- TypeScript

生成代码侧：

- Python
- Dockerfile
- 临时 venv smoke validation

## 目录结构

```text
research_code/
  backend/
    app/
      api/                      # FastAPI routes
      core/                     # 数据库、模型、存储
      llm/                      # LLM client
      services/                 # 论文分析、代码生成、向量检索、校验
      workers/                  # 上传后的后台 pipeline
    skills/                     # 项目阶段规划和实现说明
    requirements.txt

  frontend/
    app/                        # Next.js app
    components/                 # 前端组件
    lib/                        # API client
    package.json

  task_progress/                # 项目实现过程记录
  generated_projects/           # 可选生成工程目录
```

运行时数据默认写到项目外层的 `data/` 目录：

```text
data/
  uploads/                      # 上传的 PDF
  parsed/                       # 解析结果
  generated/                    # 报告、代码、code_spec、experiment_spec
  artifacts/                    # 最终 result.zip
  validation_runs/              # 临时 venv 校验目录
  qdrant/                       # 本地 Qdrant 数据
  db.sqlite3                    # SQLite 数据库
```

## 快速启动

### 1. 启动后端

```powershell
cd D:\agent开发\pdf_project\research_code\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

如果你使用 conda，也可以用已有环境：

```powershell
cd D:\agent开发\pdf_project\research_code\backend
conda activate D:\anacondadir\langchain
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 2. 启动前端

```powershell
cd D:\agent开发\pdf_project\research_code\frontend
npm install
npm run dev
```

默认访问：

```text
http://127.0.0.1:3000
```

后端默认地址：

```text
http://127.0.0.1:8000/api
```

前端会读取：

```text
NEXT_PUBLIC_API_BASE_URL
```

如果没有设置，默认使用：

```text
http://127.0.0.1:8000/api
```

## 后端环境变量

后端会读取：

```text
research_code/backend/.env
```

最小配置示例：

```env
LLM_API_KEY=your_llm_api_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4
EMBEDDING_MODEL=embedding-3
EMBEDDING_DIMENSIONS=1024

QDRANT_COLLECTION=paper_chunks
```

如果 `EMBEDDING_API_KEY` 没有配置，系统会尝试使用 `LLM_API_KEY`。

如果没有配置 `QDRANT_URL`，系统会使用本地文件模式：

```text
data/qdrant/
```

如果要连接远程 Qdrant：

```env
QDRANT_URL=http://127.0.0.1:6333
QDRANT_API_KEY=your_qdrant_api_key
QDRANT_COLLECTION=paper_chunks
```

代码生成校验相关配置：

```env
CODE_GEN_MAX_WORKERS=3
CODE_VALIDATION_TIMEOUT_SECONDS=90
CODE_VALIDATION_INSTALL_TIMEOUT_SECONDS=180
CODE_VALIDATION_KEEP_FAILED_RUNS=false
CODE_REPAIR_MAX_ATTEMPTS=3
CODE_REPAIR_MAX_TOKENS=6000
```

## 论文处理主流程

用户上传 PDF 后，后台 pipeline 大致如下：

```text
保存 PDF
-> 解析文档元素
-> 切分 chunks
-> 保存 chunks 到 SQLite
-> 写入 Qdrant 向量索引
-> LLM 分析论文
-> 生成 report.md
-> 构建 experiment_spec
-> 构建 code_spec
-> 按契约生成代码文件
-> 在临时 venv 中安装依赖和运行 smoke validation
-> 自动 repair 失败代码
-> 打包 result.zip
```

核心文件：

- `backend/app/workers/pipeline.py`
- `backend/app/services/experiment_spec_builder.py`
- `backend/app/services/experiment_frameworks.py`
- `backend/app/services/llm_code_generator.py`
- `backend/app/services/structured_python_generator.py`
- `backend/app/services/code_runner.py`
- `backend/app/services/code_repairer.py`
- `backend/app/services/vector_store.py`

## 生成代码的三层控制

为了避免 LLM 生成的多个文件互相不对应，项目使用三层控制。

### 1. experiment_spec

位置：

```text
backend/app/services/experiment_spec_builder.py
```

`experiment_spec` 是论文实验定义，描述的是“这篇论文应该跑什么实验”，而不是具体代码文件。

典型结构：

```json
{
  "experiment_type": "rl_resource_allocation_actor_critic",
  "project_type": "rl",
  "domain": "cloud_datacenter",
  "task": "resource allocation",
  "algorithm": {
    "family": "actor_critic",
    "variant": "A3C"
  },
  "environment": {
    "state": "resource usage plus current job/request features",
    "action": "choose wait/reject or assign current job/request",
    "reward": "QoS/resource efficiency minus cost"
  },
  "smoke_validation": {
    "episodes": 1,
    "steps_per_episode": 3,
    "must_use_environment": true,
    "must_use_agent": true
  }
}
```

生成后会保存到：

```text
data/generated/<project_id>/experiment_spec.json
```

### 2. experiment_framework

位置：

```text
backend/app/services/experiment_frameworks.py
```

`experiment_framework` 根据 `experiment_type` 注入稳定模块结构、类名、函数名和 symbol 依赖。

当前已支持：

```text
rl_resource_allocation_actor_critic
```

固定生成结构：

```text
src/environment.py
  CloudDatacenterEnv

src/agent.py
  ActorNetwork
  CriticNetwork
  A3CAgent

src/train.py
  train_a3c_smoke(config: dict) -> dict

src/experiment.py
  run_experiment(config: dict) -> dict
```

### 3. experiment_trace validation

位置：

```text
backend/app/services/code_runner.py
```

生成代码不是只要退出码为 0 就通过，还必须返回实验执行证据：

```json
{
  "experiment_trace": {
    "used_environment": true,
    "used_agent": true,
    "used_training_loop": true,
    "episodes_completed": 1,
    "total_steps": 3
  }
}
```

如果出现：

```json
{
  "episodes_completed": 0,
  "total_steps": 0
}
```

即使程序没有报错，也会判定生成代码无效，并进入 repair 流程。

## 如何添加新的论文类型

新增论文类型时，不要按单篇论文硬编码。正确方式是为“一类论文”添加可复用实验类型。

例如新增：

```text
rl_resource_allocation_dqn
```

它可以覆盖：

```text
DQN / DDQN
+ 资源分配 / 调度 / 卸载 / 云数据中心 / 边缘计算 / 无线网络
```

最少需要改三个位置。

### 第一步：注册实验类型识别规则

文件：

```text
backend/app/services/experiment_spec_builder.py
```

找到：

```python
EXPERIMENT_TYPE_RULES = [
    ...
]
```

添加新规则：

```python
EXPERIMENT_TYPE_RULES = [
    {
        "experiment_type": "rl_resource_allocation_actor_critic",
        "project_type": "rl",
        "prompt": "...",
        "keyword_groups": [
            ["actor-critic", "actor critic", "a3c", "a2c", "advantage actor"],
            ["resource allocation", "resource management", "scheduling", "offloading"],
        ],
    },
    {
        "experiment_type": "rl_resource_allocation_dqn",
        "project_type": "rl",
        "prompt": (
            "Use experiment_type rl_resource_allocation_dqn only when the paper is about "
            "DQN/DDQN-style reinforcement learning for resource allocation, scheduling, "
            "task offloading, or communication/computing resource management."
        ),
        "keyword_groups": [
            ["dqn", "ddqn", "deep q-network", "deep q learning"],
            ["resource allocation", "resource management", "scheduling", "offloading", "cloud", "edge", "wireless"],
        ],
    },
]
```

`keyword_groups` 的含义是：

```text
每一组至少命中一个关键词，才会识别为该类型。
```

例如上面的 DQN 类型，必须同时命中：

```text
DQN 相关词
+ 资源分配相关词
```

### 第二步：添加 fallback 默认实验定义

同一个文件：

```text
backend/app/services/experiment_spec_builder.py
```

新增默认填充函数：

```python
def _apply_dqn_resource_allocation_defaults(
    text: str,
    algorithm: dict,
    environment: dict,
    data: dict,
    training: dict,
) -> None:
    algorithm.update(
        {
            "family": "value_based_rl",
            "variant": "DQN",
            "agent": "dqn_agent",
        }
    )
    environment.update(
        {
            "entities": ["resource_pool", "job_or_request", "scheduler_agent"],
            "state": "resource usage plus current job/request features",
            "action": "choose wait/reject or assign current job/request to a resource",
            "reward": "combine service quality/resource efficiency objective with resource or energy cost",
            "dynamics": "advance one job/request per step and update resource availability",
        }
    )
    data.update(
        {
            "fallback": "synthetic resource-allocation trace with servers/resources, jobs, demands, and durations",
        }
    )
    training.update(
        {
            "loop": "Run epsilon-greedy interaction, store transitions in replay buffer, and update Q-network from sampled batches.",
            "update_rule": "Bellman TD target update for Q-network",
            "metrics": ["episodes_completed", "total_steps", "total_reward", "average_reward"],
        }
    )
```

然后注册：

```python
EXPERIMENT_FALLBACK_APPLIERS = {
    "rl_resource_allocation_actor_critic": _apply_actor_critic_resource_allocation_defaults,
    "rl_resource_allocation_dqn": _apply_dqn_resource_allocation_defaults,
}
```

这一步用于 LLM 输出不稳定或识别失败时的兜底。

### 第三步：添加框架 builder

文件：

```text
backend/app/services/experiment_frameworks.py
```

新增一个框架 builder：

```python
def _rl_resource_allocation_dqn_framework(experiment_spec: dict) -> dict:
    smoke = experiment_spec.get("smoke_validation") if isinstance(experiment_spec.get("smoke_validation"), dict) else {}
    episodes = smoke.get("episodes", 1)
    steps_per_episode = smoke.get("steps_per_episode", 3)

    return {
        "framework": "rl_resource_allocation_dqn",
        "project_type": "rl",
        "files": [
            {"path": "README.md", "purpose": "Explain the generated experiment project.", "kind": "document"},
            {"path": "requirements.txt", "purpose": "Declare Python dependencies.", "kind": "dependency"},
            {"path": "Dockerfile", "purpose": "Build a reproducible runtime environment.", "kind": "docker"},
            {"path": "config.json", "purpose": "Runtime configuration for the smoke experiment.", "kind": "config"},
            {"path": "main.py", "purpose": "Command-line entrypoint.", "kind": "entrypoint"},
            {"path": "src/environment.py", "purpose": "Resource-allocation environment.", "kind": "code"},
            {"path": "src/agent.py", "purpose": "DQN agent, replay buffer, and Q network.", "kind": "code"},
            {"path": "src/train.py", "purpose": "Short DQN smoke training loop.", "kind": "code"},
            {"path": "src/experiment.py", "purpose": "One-stop experiment orchestration.", "kind": "code"},
        ],
        "dependencies": ["numpy", "torch"],
        "config": {
            "episodes": episodes,
            "steps_per_episode": steps_per_episode,
            "learning_rate": 0.001,
            "gamma": 0.95,
            "epsilon": 0.1,
            "replay_capacity": 1000,
        },
        "interfaces": {
            "environment": {
                "class_name": "ResourceAllocationEnv",
            },
            "agent": {
                "class_name": "DQNAgent",
                "required_methods": ["select_action", "store_transition", "train_step", "save"],
            },
            "training": {
                "function_name": "train_dqn_smoke",
                "signature": "train_dqn_smoke(config: dict) -> dict",
            },
            "experiment": {
                "function_name": "run_experiment",
                "signature": "run_experiment(config: dict) -> dict",
            },
        },
        "module_contracts": [
            # src/environment.py, src/agent.py, src/train.py, src/experiment.py 的 exports
        ],
        "symbols": [
            # ResourceAllocationEnv / QNetwork / ReplayBuffer / DQNAgent / train_dqn_smoke / run_experiment
        ],
        "expected_outputs": ["outputs/smoke_result.json"],
        "assumptions": [
            "The framework runs a smoke-sized DQN experiment, not full paper-scale reproduction.",
        ],
        "missing_details": [
            "Exact replay settings, benchmark data, and production hyperparameters may need manual completion.",
        ],
    }
```

然后注册：

```python
FRAMEWORK_BUILDERS = {
    "rl_resource_allocation_actor_critic": _rl_resource_allocation_actor_critic_framework,
    "rl_resource_allocation_dqn": _rl_resource_allocation_dqn_framework,
}
```

`module_contracts` 和 `symbols` 是最关键的两部分。

`module_contracts` 决定生成哪些类和函数：

```text
src/environment.py
  ResourceAllocationEnv

src/agent.py
  QNetwork
  ReplayBuffer
  DQNAgent

src/train.py
  train_dqn_smoke

src/experiment.py
  run_experiment
```

`symbols` 决定跨文件依赖和自动 import：

```text
train_dqn_smoke depends_on:
  ResourceAllocationEnv
  DQNAgent

run_experiment depends_on:
  train_dqn_smoke
```

如果 `symbols` 写对，生成器会自动管理类似这样的 import：

```python
from src.environment import ResourceAllocationEnv
from src.agent import DQNAgent
from src.train import train_dqn_smoke
```

### 第四步：按需添加 trace validator

文件：

```text
backend/app/services/code_runner.py
```

如果新类型仍然是 RL，并且能返回下面这种 trace：

```json
{
  "experiment_trace": {
    "used_environment": true,
    "used_agent": true,
    "used_training_loop": true,
    "episodes_completed": 1,
    "total_steps": 3
  }
}
```

通常不需要新增 validator。

如果新类型是 ML、优化、仿真，并且 trace 结构不同，就新增一个 validator：

```python
def _validate_ml_experiment_trace(spec: dict, trace: dict) -> list[dict]:
    diagnostics = []
    if trace.get("used_dataset") is not True:
        diagnostics.append(_experiment_diagnostic("dataset_not_used", "experiment_trace.used_dataset must be true"))
    if trace.get("used_model") is not True:
        diagnostics.append(_experiment_diagnostic("model_not_used", "experiment_trace.used_model must be true"))
    if trace.get("used_training_loop") is not True:
        diagnostics.append(_experiment_diagnostic("training_loop_not_used", "experiment_trace.used_training_loop must be true"))
    if _safe_int(trace.get("epochs_completed"), 0) < 1:
        diagnostics.append(_experiment_diagnostic("epochs_not_completed", "experiment_trace.epochs_completed must be at least 1"))
    return diagnostics
```

然后注册：

```python
TRACE_VALIDATORS = {
    "rl_resource_allocation_actor_critic": _validate_rl_experiment_trace,
    "ml_classification": _validate_ml_experiment_trace,
}
```

## 新类型开发建议

添加新类型时，建议按这个顺序做：

```text
1. 先定义 experiment_type 名称
2. 写 EXPERIMENT_TYPE_RULES
3. 写 fallback applier
4. 写 framework builder
5. 写 module_contracts
6. 写 symbols
7. 如有必要，写 trace validator
8. 用小对象本地验证注册和 code_spec 结构
9. 再上传真实 PDF 跑完整流程
```

最小本地验证示例：

```powershell
cd D:\agent开发\pdf_project\research_code\backend
python -c "from app.services.experiment_spec_builder import registered_experiment_types; from app.services.experiment_frameworks import registered_experiment_frameworks; from app.services.code_runner import registered_trace_validators; print(registered_experiment_types()); print(registered_experiment_frameworks()); print(registered_trace_validators())"
```

检查某个框架是否能注入：

```powershell
cd D:\agent开发\pdf_project\research_code\backend
python -c "from app.services.experiment_frameworks import apply_experiment_framework; e={'experiment_type':'rl_resource_allocation_actor_critic','project_type':'rl','smoke_validation':{'episodes':1,'steps_per_episode':3}}; s=apply_experiment_framework({}, e); print(s['framework']); print([c['path'] for c in s['module_contracts']]); print([x['name'] for c in s['module_contracts'] for x in c['exports']])"
```

预期输出类似：

```text
rl_resource_allocation_actor_critic
['src/environment.py', 'src/agent.py', 'src/train.py', 'src/experiment.py']
['CloudDatacenterEnv', 'ActorNetwork', 'CriticNetwork', 'A3CAgent', 'train_a3c_smoke', 'run_experiment']
```

## 生成结果

每个项目生成完成后，主要结果在：

```text
data/generated/<project_id>/
  report.md
  experiment_spec.json
  code_spec.json
  code_plan.json
  validation_result.json
  code/
    README.md
    requirements.txt
    Dockerfile
    config.json
    main.py
    src/
```

最终压缩包在：

```text
data/artifacts/<project_id>/result.zip
```

解压后可以本地运行：

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py --config config.json
```

也可以使用生成工程里的 Dockerfile：

```powershell
docker build -t generated_research_code .
docker run --rm -v "%cd%\outputs:/app/outputs" generated_research_code
```

Docker 运行时依赖安装在镜像/容器中，不会安装到本机 Python 环境。挂载的 `outputs` 目录会写入本机当前目录下的 `outputs`。

## 注意事项

- 生成代码的目标是先跑通 smoke experiment，不保证完整复现论文指标。
- 如果论文没有公开数据集，生成代码会使用结构相似的 synthetic data。
- 真实复现实验通常还需要手动补充数据预处理、完整超参数、baseline 和评估脚本。
- 后端 validation 会创建临时 venv，安装生成代码依赖，运行结束后默认清理。
- 如果需要保留失败现场，可以设置：

```env
CODE_VALIDATION_KEEP_FAILED_RUNS=true
```

失败现场会保留在：

```text
data/validation_runs/
```

