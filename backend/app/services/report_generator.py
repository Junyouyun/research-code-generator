def generate_report(analysis: dict) -> str:
    final_summary = analysis.get("final_summary") or {}
    if final_summary:
        return _generate_final_summary_report(analysis, final_summary)

    return _generate_legacy_report(analysis)


def _generate_final_summary_report(analysis: dict, final_summary: dict) -> str:
    lines = [
        "# 研究报告",
        "",
        "## 1. 论文标题",
        _text(final_summary.get("title") or analysis.get("title")),
        "",
        "## 2. 一句话总结",
        _text(final_summary.get("one_sentence_summary")),
        "",
        "## 3. 总体摘要",
        _text(final_summary.get("executive_summary")),
        "",
        "## 4. 研究问题",
        _text(final_summary.get("research_problem")),
        "",
        "## 5. 方法概览",
        _text(final_summary.get("method_overview")),
        "",
        "## 6. 实验或论证总结",
        _text(final_summary.get("experiment_or_argument_summary")),
        "",
        "## 7. 主要发现",
        _bullet_list(final_summary.get("main_findings")),
        "",
        "## 8. 局限与风险",
        _bullet_list(final_summary.get("limitations")),
        "",
        "## 9. 复现与代码相关性",
        _text(final_summary.get("code_relevance")),
        "",
        "## 10. 复现注意事项",
        _bullet_list(final_summary.get("reproducibility_notes")),
        "",
        "## 11. 建议代码结构",
        _module_list(analysis.get("possible_code_modules")),
        "",
    ]
    return "\n".join(lines)


def _generate_legacy_report(analysis: dict) -> str:
    planner_review = _planner_review(analysis)

    lines = [
        "# 研究报告",
        "",
        "## 1. 论文标题",
        _text(analysis.get("title")),
        "",
        "## 2. 摘要",
        _text(analysis.get("abstract")),
        "",
        "## 3. 研究问题",
        _text(analysis.get("research_problem")),
        "",
        "## 4. 主要贡献",
        _bullet_list(analysis.get("main_contribution")),
        "",
        "## 5. 方法总结",
        _text(analysis.get("method_summary")),
        "",
        "## 6. 实验或论证总结",
        _text(analysis.get("experiment_summary")),
        "",
        "## 7. 可复现部分",
        _bullet_list(analysis.get("reproducible_parts")),
        "",
        "## 8. 多 Agent 评审结论",
        _agent_review(analysis, planner_review),
        "",
        "## 9. 建议代码结构",
        _module_list(analysis.get("possible_code_modules")),
        "",
        "## 10. 需要的输入或前置条件",
        _bullet_list(analysis.get("required_inputs")),
        "",
    ]
    return "\n".join(lines)


def _planner_review(analysis: dict) -> dict:
    if analysis.get("agent_dialogue"):
        return analysis.get("agent_dialogue", {}).get("planner_review", {})
    return analysis.get("debug", {}).get("agent_dialogue", {}).get("planner_review", {})


def _agent_review(analysis: dict, planner_review: dict) -> str:
    lines = [
        f"- 代码生成策略：{analysis.get('code_generation_strategy', 'analysis_tool')}",
        f"- 复现风险：{analysis.get('reproducibility_risk', 'medium')}",
    ]

    final_judgement = planner_review.get("final_judgement")
    if final_judgement:
        lines.append(f"- 综合判断：{final_judgement}")

    recommended_code_strategy = planner_review.get("recommended_code_strategy")
    if recommended_code_strategy:
        lines.append(f"- 代码建议：{recommended_code_strategy}")

    risks = planner_review.get("risks") or []
    if risks:
        lines.append("- 风险：")
        lines.extend(f"  - {item}" for item in risks)

    missing_information = planner_review.get("missing_information") or []
    if missing_information:
        lines.append("- 缺失信息：")
        lines.extend(f"  - {item}" for item in missing_information)

    return "\n".join(lines)


def _text(value: str | None) -> str:
    if not value:
        return "暂无明确内容。"
    return str(value).strip()


def _bullet_list(values: list[str] | None) -> str:
    if not values:
        return "- 暂无明确内容。"
    return "\n".join(f"- {value}" for value in values)


def _module_list(modules: list[dict] | None) -> str:
    if not modules:
        return "- 暂无明确代码模块。"

    lines = []
    for module in modules:
        name = module.get("name", "unknown.py")
        purpose = module.get("purpose", "未说明")
        lines.append(f"- `{name}`：{purpose}")

    return "\n".join(lines)
