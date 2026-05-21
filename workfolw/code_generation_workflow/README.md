# 代码生成流程设计

## 目标

当前代码生成只输出“能运行的保守模板”，不能满足项目核心目标。

新的目标是：基于论文解析结果、语义 chunks、LLM 总结和多 agent 评审，生成一个尽可能完整、详细、可运行的代码项目；如果论文缺少关键细节，也要明确写出假设，而不是生成空壳代码。

## 第一阶段：代码需求提取

输入：

- `analysis.json`
- SQLite 中的 `document_chunks`
- 文档元素中的公式、表格、图片说明、算法段落

要提取的内容：

- 论文要解决的问题
- 方法或算法流程
- 状态空间、动作空间、奖励函数、损失函数等可编码定义
- 数据集、仿真环境、输入输出格式
- 训练参数、实验参数、评价指标
- baseline 或对比方法
- 论文未给出的关键缺失信息

输出：

- `code_requirements`
- `implementation_assumptions`
- `missing_details`

这一阶段不写代码，只判断“应该写什么代码”。

## 第二阶段：生成 code_spec

`code_spec` 是代码生成前的结构化设计，不直接等同于最终代码。

建议结构：

```json
{
  "project_type": "deep_reinforcement_learning_simulation",
  "framework": "pytorch",
  "entry_command": "python main.py --config config.json",
  "docker": true,
  "files": [
    {
      "path": "main.py",
      "purpose": "CLI entrypoint"
    },
    {
      "path": "src/environment.py",
      "purpose": "simulation environment"
    }
  ],
  "dependencies": ["numpy", "torch", "matplotlib"],
  "assumptions": [],
  "missing_details": []
}
```

这一阶段决定：

- 生成哪些文件
- 每个文件负责什么
- 使用什么框架
- 是否需要 Docker
- 哪些地方是论文明确给出的
- 哪些地方是合理假设

## 第三阶段：逐文件生成代码

输入：

- `code_spec`
- 与当前文件相关的 chunks
- `analysis.final_summary`
- 多 agent 评审结果

生成原则：

- 先生成 `requirements.txt`、`Dockerfile`、`config.json`
- 再生成核心模块
- 最后生成 `main.py` 和 `README.md`
- 每个文件只接收自己需要的上下文，避免 prompt 过大
- 代码里允许写少量注释说明论文缺失参数和默认假设

对于深度强化学习论文，可能生成：

```text
README.md
Dockerfile
requirements.txt
config.json
main.py
src/environment.py
src/replay_buffer.py
src/ddqn_agent.py
src/train.py
src/evaluate.py
src/baselines.py
```

对于普通算法论文，可能生成：

```text
README.md
Dockerfile
requirements.txt
config.json
main.py
src/algorithm.py
src/data.py
src/metrics.py
src/visualize.py
```

对于纯理论或缺少实现细节的论文，生成：

```text
README.md
Dockerfile
requirements.txt
config.json
main.py
src/model.py
src/experiment_stub.py
```

但必须在 README 和代码注释中明确说明哪些内容来自论文，哪些是默认假设。

## 第四阶段：静态检查和打包

当前阶段先做轻量检查，不直接运行完整实验。

检查内容：

- Python 文件是否能通过 `compileall`
- 文件清单是否完整
- `requirements.txt` 是否存在
- `Dockerfile` 是否存在
- `README.md` 是否包含运行命令
- `main.py` 是否存在入口函数

后续可以增强为：

- Docker build
- Docker run smoke test
- 运行失败后把错误回传给 LLM 自动修复

## 关键变化

旧流程：

```text
analysis -> 固定 5 个模板文件 -> 打包
```

新流程：

```text
analysis + chunks -> code_requirements -> code_spec -> 逐文件生成 -> 检查 -> 打包
```

旧流程保证“能跑”，但代码没有论文实现价值。

新流程优先保证“贴近论文、可读、可扩展、能实验”，再通过 Docker 和 smoke test 提高可运行性。

