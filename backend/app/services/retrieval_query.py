from __future__ import annotations

import re


QUERY_RULES = [
    {
        "intent": "action_space",
        "keywords": {
            "action",
            "actions",
            "action space",
            "动作",
            "动作空间",
            "决策",
            "分配",
            "调度",
        },
        "queries": [
            "action space scheduling decision job scheduler server assignment",
            "job scheduling action select execute jobs from job sequence to server",
            "allocation decision control action resource allocation scheduling decision",
            "A = {0, 1, 2, ..., m} action space cloud resource allocation",
            "whether a job will be processed by a server or wait in the job sequence",
        ],
        "target_sections": ["system model", "method", "mdp", "problem formulation"],
        "target_entity_types": ["action", "environment"],
    },
    {
        "intent": "state_space",
        "keywords": {
            "state",
            "states",
            "state space",
            "observation",
            "状态",
            "状态空间",
            "观测",
        },
        "queries": [
            "state space resource usage resource requests arrived jobs durations",
            "state st consists of resource usage of all servers and resource requests",
            "Ures Ores Djob state definition cloud datacenter",
            "MDP state space cloud resource allocation server state job state",
            "occupancy requests job durations resource usage by timestep",
        ],
        "target_sections": ["system model", "method", "mdp", "problem formulation"],
        "target_entity_types": ["state", "environment"],
    },
    {
        "intent": "reward_function",
        "keywords": {
            "reward",
            "rewards",
            "reward function",
            "objective",
            "utility",
            "cost",
            "penalty",
            "optimization target",
            "奖励",
            "回报",
            "目标函数",
            "优化目标",
            "代价",
            "惩罚",
        },
        "queries": [
            "reward function total rewards QoS energy efficiency RQoS Renergy",
            "objective function utility cost penalty optimization target",
            "reward consists of QoS rewards and energy efficiency rewards",
            "latency penalty job waiting execution dismissing energy consumption penalty",
            "Rt RQoS Renergy cloud resource allocation reward definition",
        ],
        "target_sections": ["system model", "method", "mdp", "training"],
        "target_entity_types": ["reward", "objective"],
    },
    {
        "intent": "experiment_setup",
        "keywords": {
            "experiment",
            "experiments",
            "setting",
            "settings",
            "setup",
            "dataset",
            "data",
            "trace",
            "simulation",
            "hyperparameter",
            "实验",
            "实验设置",
            "数据集",
            "数据",
            "仿真",
            "参数",
        },
        "queries": [
            "performance evaluation settings datasets simulation experiments",
            "TensorFlow 1.4.0 cloud datacenter simulated with 50 heterogeneous servers",
            "Google cloud datacenter trace data May 2011 125000 servers",
            "training process 10 DRL agents batch size hidden layers epochs learning rate",
            "simulation setup real-world trace data Google cloud datacenters",
        ],
        "target_sections": ["performance evaluation", "settings", "datasets", "experiments"],
        "target_entity_types": ["dataset", "experiment"],
    },
    {
        "intent": "baselines",
        "keywords": {
            "baseline",
            "baselines",
            "compare",
            "comparison",
            "compared",
            "对比",
            "比较",
            "基线",
            "baseline方法",
            "对照",
        },
        "queries": [
            "comparative experiments baselines Random LJF SJF RR Tetris PG DQL",
            "classic algorithms evaluated Random Longest job first Shortest job first Round-robin Tetris",
            "advanced DRL based methods PG DQL compared with proposed A3C",
            "resource allocation baseline methods performance comparison",
            "five classic algorithms and two advanced DRL-based methods",
        ],
        "target_sections": ["performance evaluation", "comparison", "experiments"],
        "target_entity_types": ["baseline", "method"],
    },
    {
        "intent": "metrics_results",
        "keywords": {
            "metric",
            "metrics",
            "result",
            "results",
            "performance",
            "latency",
            "energy",
            "dismissing",
            "评价指标",
            "指标",
            "结果",
            "性能",
            "延迟",
            "能耗",
        },
        "queries": [
            "performance metrics normalized average job latency average energy consumption job dismissing rate",
            "QoS latency dismissing rate energy efficiency average energy consumption results",
            "Table performance metrics latency energy dismissing rate A3C based DRL",
            "comparison results total rewards convergence QoS energy efficiency",
            "proposed method outperforms classic resource allocation methods PG DQL",
        ],
        "target_sections": ["results", "performance evaluation", "comparison"],
        "target_entity_types": ["metric", "result"],
    },
    {
        "intent": "training_process",
        "keywords": {
            "train",
            "training",
            "algorithm",
            "actor",
            "critic",
            "a3c",
            "asynchronous",
            "训练",
            "算法",
            "异步",
            "流程",
        },
        "queries": [
            "A3C training process actor critic TD error advantage function asynchronous update",
            "Algorithm 1 A3C based resource allocation actor network critic network",
            "Algorithm 2 asynchronous update policy parameters RMSProp global local parameters",
            "actor choose action critic value function policy gradient advantage function",
            "multiple DRL agents asynchronously update policy parameters",
        ],
        "target_sections": ["method", "algorithm", "training"],
        "target_entity_types": ["algorithm", "training_step"],
    },
    {
        "intent": "system_model",
        "keywords": {
            "system model",
            "model",
            "environment",
            "ras",
            "resource allocation system",
            "系统模型",
            "模型",
            "环境",
            "资源分配系统",
        },
        "queries": [
            "system model cloud datacenter resource allocation RAS DRL based resource controller",
            "resource allocation system job scheduler information collector energy agent",
            "cloud datacenter environment servers resources jobs job sequence",
            "DRL based resource controller generates policies of job scheduling",
            "unified model of resource allocation QoS energy efficiency dynamic environments",
        ],
        "target_sections": ["system model", "problem formulation"],
        "target_entity_types": ["environment", "method"],
    },
    {
        "intent": "problem_goal",
        "keywords": {
            "problem",
            "goal",
            "objective",
            "contribution",
            "解决",
            "问题",
            "目标",
            "贡献",
            "主要",
            "优化目标",
        },
        "queries": [
            "adaptive efficient cloud resource allocation low latency energy efficiency QoS",
            "dynamic cloud environments resource allocation excessive energy consumption degraded QoS",
            "optimization goals job latency dismissing rate average energy consumption",
            "main contributions unified model A3C resource allocation real-world Google cloud datacenter trace",
            "actor critic deep reinforcement learning cloud resource allocation scheme",
        ],
        "target_sections": ["abstract", "introduction", "contributions"],
        "target_entity_types": ["objective", "method"],
    },
]

DEFAULT_QUERIES = [
    "paper method problem formulation experiment setting key technical details",
    "method state action reward dataset metrics results",
]


def build_retrieval_queries(
    question: str,
    paper_type: str | None = None,
    max_queries: int = 6,
) -> dict:
    original_query = _clean_query(question)
    if not original_query:
        return {
            "original_query": "",
            "intent": "general",
            "question_type": "general",
            "expanded_queries": [],
            "target_sections": [],
            "target_entity_types": [],
        }

    matched_rule = _best_rule(original_query)
    intent = matched_rule["intent"] if matched_rule else "general"
    expanded_queries = [original_query]
    expanded_queries.extend(matched_rule["queries"] if matched_rule else DEFAULT_QUERIES)

    if paper_type and "rl" in paper_type.lower():
        expanded_queries.append("reinforcement learning MDP state action reward policy training")

    expanded_queries = _dedupe_queries(expanded_queries)[:max_queries]
    return {
        "original_query": original_query,
        "intent": intent,
        "question_type": intent,
        "expanded_queries": expanded_queries,
        "target_sections": list(matched_rule["target_sections"] if matched_rule else []),
        "target_entity_types": list(matched_rule["target_entity_types"] if matched_rule else []),
    }


def _best_rule(question: str) -> dict | None:
    lowered = question.lower()
    best_rule = None
    best_score = 0
    for rule in QUERY_RULES:
        score = sum(1 for keyword in rule["keywords"] if keyword.lower() in lowered)
        if score > best_score:
            best_rule = rule
            best_score = score
    return best_rule


def _clean_query(query: str) -> str:
    return re.sub(r"\s+", " ", str(query or "")).strip()


def _dedupe_queries(queries: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for query in queries:
        cleaned = _clean_query(query)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped
