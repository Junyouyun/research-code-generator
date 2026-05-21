import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from app.config import DEFAULT_AGENT_DIALOGUE_ROUNDS, DEFAULT_AGENT_MAX_WORKERS, DEFAULT_LLM_MAX_WORKERS
from app.llm.client import chat_completion


SECTION_MAX_INPUT_TOKENS = 4000
ProgressCallback = Callable[[str], None]

DIALOGUE_AGENTS = ["method_agent", "experiment_agent", "code_agent", "critic_agent"]
DIALOGUE_AGENT_DESCRIPTIONS = {
    "method_agent": "关注论文的方法、理论框架、流程、算法和关键假设。",
    "experiment_agent": "关注实验、案例、数据来源、评估指标和验证充分性。",
    "code_agent": "关注哪些内容可以转成代码、需要哪些模块、哪些只能生成模板或辅助工具。",
    "critic_agent": "关注缺失信息、过度推断、不可复现点和报告风险。",
}


def analyze_paper_with_llm(
    parsed_paper: dict,
    chunks: list[dict],
    progress_callback: ProgressCallback | None = None,
) -> tuple[dict, list[dict]]:
    from app.services.llm_analysis_graph import run_llm_analysis_graph

    return run_llm_analysis_graph(parsed_paper, chunks, progress_callback)


def summarize_chunk(chunk: dict) -> dict:
    """保留旧接口：单个 chunk 会被当成只有一个 section 的任务。"""
    unit = _make_section_unit("single_chunk", [chunk], 1)
    return summarize_section_unit(unit)


def summarize_section_unit(unit: dict) -> dict:
    agent_role = _agent_role_for_section(unit["title"], unit["hierarchy_path"])
    messages = [
        {
            "role": "system",
            "content": (
                f"你是一个论文 section 分析 agent，当前角色是：{agent_role}。\n"
                "你只分析用户给出的 section chunks，不要补充原文没有的信息。\n"
                "请提取与该角色相关的研究问题、方法、实验、结果和代码复现线索。\n"
                "必须只返回 JSON，不要输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请分析下面的 section，并返回 JSON。\n"
                "JSON 字段必须包含：summary, key_points, methods, experiments, code_hints, open_questions。\n"
                "summary 用中文，控制在 150-300 字。\n"
                "key_points/methods/experiments/code_hints/open_questions 都是字符串数组。\n\n"
                f"section_id: {unit['section_id']}\n"
                f"section_title: {unit['title']}\n"
                f"hierarchy_path: {unit['hierarchy_path']}\n"
                f"agent_role: {agent_role}\n"
                f"pages: {unit.get('page_start')}-{unit.get('page_end')}\n"
                f"chunk_ids: {', '.join(unit['chunk_ids'])}\n\n"
                f"section_chunks:\n{unit['content']}"
            ),
        },
    ]
    data = _chat_json(messages, max_tokens=2200)

    return {
        "summary_type": "section",
        "section_id": unit["section_id"],
        "chunk_id": unit["section_id"],
        "chunk_ids": unit["chunk_ids"],
        "title": unit["title"],
        "hierarchy_path": unit["hierarchy_path"],
        "agent_role": agent_role,
        "page_start": unit.get("page_start"),
        "page_end": unit.get("page_end"),
        "summary": _as_text(data.get("summary")),
        "key_points": _as_string_list(data.get("key_points")),
        "methods": _as_string_list(data.get("methods")),
        "experiments": _as_string_list(data.get("experiments")),
        "code_hints": _as_string_list(data.get("code_hints")),
        "open_questions": _as_string_list(data.get("open_questions")),
    }


def run_agent_dialogue(
    section_summaries: list[dict],
    progress_callback: ProgressCallback | None = None,
) -> dict:
    rounds_count = _agent_dialogue_rounds()
    if not section_summaries or rounds_count <= 0:
        return {"round_count": 0, "rounds": [], "planner_review": {}}

    if progress_callback:
        progress_callback(f"开始多 agent 交互：{rounds_count} 轮，{len(DIALOGUE_AGENTS)} 个角色")

    rounds = []
    previous_messages: list[dict] = []
    for round_number in range(1, rounds_count + 1):
        if progress_callback:
            progress_callback(f"多 agent 第 {round_number} 轮开始")
        messages = _run_dialogue_round(round_number, section_summaries, previous_messages, progress_callback)
        rounds.append({"round": round_number, "messages": messages})
        previous_messages = messages

    planner_review = build_planner_review(section_summaries, rounds)
    if progress_callback:
        progress_callback("planner_agent 完成最终汇总")

    return {
        "round_count": rounds_count,
        "agents": DIALOGUE_AGENTS,
        "rounds": rounds,
        "planner_review": planner_review,
    }


def _run_dialogue_round(
    round_number: int,
    section_summaries: list[dict],
    previous_messages: list[dict],
    progress_callback: ProgressCallback | None,
) -> list[dict]:
    max_workers = min(_agent_max_workers(), len(DIALOGUE_AGENTS))
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(review_with_role_agent, agent_name, section_summaries, previous_messages, round_number): agent_name
            for agent_name in DIALOGUE_AGENTS
        }
        for future in as_completed(futures):
            agent_name = futures[future]
            results[agent_name] = future.result()
            if progress_callback:
                progress_callback(f"{agent_name} 完成 round {round_number}")

    return [results[agent_name] for agent_name in DIALOGUE_AGENTS if agent_name in results]


def review_with_role_agent(
    agent_name: str,
    section_summaries: list[dict],
    previous_messages: list[dict],
    round_number: int,
) -> dict:
    compact_sections = _compact_section_summaries(section_summaries)
    previous_context = _compact_agent_messages(previous_messages)
    messages = [
        {
            "role": "system",
            "content": (
                f"你是多 agent 评审中的 {agent_name}。\n"
                f"你的职责：{DIALOGUE_AGENT_DESCRIPTIONS[agent_name]}\n"
                "你要基于 section summaries 和上一轮其他 agent 的观点进行判断。\n"
                "如果是第 2 轮或之后，你需要指出自己是否修正了上一轮判断。\n"
                "必须只返回 JSON，不要输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"当前轮次：{round_number}\n\n"
                "请返回 JSON，字段必须包含：summary, claims, disagreements, risks, code_implications, questions, confidence。\n"
                "claims/disagreements/risks/code_implications/questions 都是字符串数组。\n"
                "confidence 只能是 low、medium、high。\n\n"
                "Keep summary under 180 Chinese characters. Each array must contain at most 4 short strings. Return complete JSON only.\n\n"
                f"section_summaries:\n{json.dumps(compact_sections, ensure_ascii=False)}\n\n"
                f"previous_agent_messages:\n{json.dumps(previous_context, ensure_ascii=False)}"
            ),
        },
    ]
    data = _chat_json(messages, max_tokens=3000)
    confidence = _as_text(data.get("confidence")).lower()

    return {
        "agent": agent_name,
        "round": round_number,
        "summary": _as_text(data.get("summary")),
        "claims": _as_string_list(data.get("claims")),
        "disagreements": _as_string_list(data.get("disagreements")),
        "risks": _as_string_list(data.get("risks")),
        "code_implications": _as_string_list(data.get("code_implications")),
        "questions": _as_string_list(data.get("questions")),
        "confidence": confidence if confidence in {"low", "medium", "high"} else "medium",
    }


def build_planner_review(section_summaries: list[dict], rounds: list[dict]) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "你是 planner_agent，负责综合多轮 agent 评审结果。\n"
                "你要判断论文适合生成什么类型的代码，以及报告应该如何保守表达。\n"
                "必须只返回 JSON，不要输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请综合 section summaries 和多轮 agent 对话，返回 JSON。\n"
                "JSON 字段必须包含：final_judgement, recommended_code_strategy, code_generation_strategy, "
                "reproducibility_risk, report_focus, code_modules, risks, missing_information。\n"
                "code_generation_strategy 只能是 algorithm_reproduction、analysis_tool、report_template、not_recommended。\n"
                "reproducibility_risk 只能是 low、medium、high。\n"
                "code_modules 是对象数组，每个对象包含 name 和 purpose。\n"
                "risks/missing_information 是字符串数组。\n\n"
                f"section_summaries:\n{json.dumps(_compact_section_summaries(section_summaries), ensure_ascii=False)}\n\n"
                f"agent_rounds:\n{json.dumps(rounds, ensure_ascii=False)}"
            ),
        },
    ]
    data = _chat_json(messages, max_tokens=2800)
    strategy = _as_text(data.get("code_generation_strategy"))
    risk = _as_text(data.get("reproducibility_risk")).lower()

    if strategy not in {"algorithm_reproduction", "analysis_tool", "report_template", "not_recommended"}:
        strategy = "analysis_tool"

    return {
        "agent": "planner_agent",
        "final_judgement": _as_text(data.get("final_judgement")),
        "recommended_code_strategy": _as_text(data.get("recommended_code_strategy")),
        "code_generation_strategy": strategy,
        "reproducibility_risk": risk if risk in {"low", "medium", "high"} else "medium",
        "report_focus": _as_text(data.get("report_focus")),
        "code_modules": _normalize_modules(data.get("code_modules")),
        "risks": _as_string_list(data.get("risks")),
        "missing_information": _as_string_list(data.get("missing_information")),
    }


def build_global_analysis(
    parsed_paper: dict,
    section_summaries: list[dict],
    agent_dialogue: dict | None = None,
) -> dict:
    compact_summaries = _compact_section_summaries(section_summaries)
    planner_review = (agent_dialogue or {}).get("planner_review", {})
    messages = [
        {
            "role": "system",
            "content": (
                "你是全局论文分析 agent。\n"
                "你会收到 section agent 摘要和多 agent 交互评审，请整合成面向报告和代码生成的总分析。\n"
                "不要编造论文没有的信息。不确定的内容要保守表达。\n"
                "必须只返回 JSON，不要输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请生成全局分析 JSON。\n"
                "JSON 字段必须包含：title, abstract, research_problem, main_contribution, "
                "method_summary, experiment_summary, reproducible_parts, required_inputs, possible_code_modules。\n"
                "main_contribution/reproducible_parts/required_inputs 是字符串数组。\n"
                "possible_code_modules 是对象数组，每个对象包含 name 和 purpose。\n\n"
                f"title_candidate: {parsed_paper.get('title', '')}\n"
                f"abstract_candidate: {parsed_paper.get('abstract', '')}\n\n"
                f"section_summaries:\n{json.dumps(compact_summaries, ensure_ascii=False)}\n\n"
                f"planner_review:\n{json.dumps(planner_review, ensure_ascii=False)}"
            ),
        },
    ]
    data = _chat_json(messages, max_tokens=3200)

    possible_code_modules = _normalize_modules(data.get("possible_code_modules"))
    if not possible_code_modules and planner_review.get("code_modules"):
        possible_code_modules = planner_review["code_modules"]

    return {
        "title": _as_text(data.get("title")) or parsed_paper.get("title", ""),
        "abstract": _as_text(data.get("abstract")) or parsed_paper.get("abstract", ""),
        "research_problem": _as_text(data.get("research_problem")),
        "main_contribution": _as_string_list(data.get("main_contribution")),
        "method_summary": _as_text(data.get("method_summary")),
        "experiment_summary": _as_text(data.get("experiment_summary")),
        "reproducible_parts": _as_string_list(data.get("reproducible_parts")),
        "required_inputs": _as_string_list(data.get("required_inputs")),
        "possible_code_modules": possible_code_modules,
        "chunk_summary_count": len(section_summaries),
        "section_summary_count": len(section_summaries),
        "agent_dialogue": agent_dialogue or {},
        "code_generation_strategy": planner_review.get("code_generation_strategy", "analysis_tool"),
        "reproducibility_risk": planner_review.get("reproducibility_risk", "medium"),
        "source": parsed_paper.get("source", ""),
        "analysis_source": "section_agents_with_dialogue",
    }


def build_final_summary(analysis: dict, section_summaries: list[dict], agent_dialogue: dict) -> dict:
    planner_review = agent_dialogue.get("planner_review", {})
    summary_input = {
        "global_analysis": {
            "title": analysis.get("title", ""),
            "abstract": analysis.get("abstract", ""),
            "research_problem": analysis.get("research_problem", ""),
            "main_contribution": analysis.get("main_contribution", []),
            "method_summary": analysis.get("method_summary", ""),
            "experiment_summary": analysis.get("experiment_summary", ""),
            "reproducible_parts": analysis.get("reproducible_parts", []),
            "required_inputs": analysis.get("required_inputs", []),
            "possible_code_modules": analysis.get("possible_code_modules", []),
            "code_generation_strategy": analysis.get("code_generation_strategy", "analysis_tool"),
            "reproducibility_risk": analysis.get("reproducibility_risk", "medium"),
        },
        "section_summaries": _compact_section_summaries(section_summaries),
        "planner_review": planner_review,
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是最终研究报告总结 agent。你会收到全局分析、章节总结和多 agent 评审结论。\n"
                "你的任务是把它们压缩成一份清晰、少重复、适合直接生成报告的中文总结。\n"
                "不要编造原文没有的信息，不确定的内容要保守表达。\n"
                "必须只返回 JSON，不要输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请生成最终总结 JSON，字段必须包含：title, one_sentence_summary, executive_summary, "
                "research_problem, method_overview, experiment_or_argument_summary, main_findings, "
                "limitations, reproducibility_notes, code_relevance, report_outline。\n"
                "main_findings/limitations/reproducibility_notes/report_outline 都是字符串数组。\n"
                "executive_summary 控制在 400-800 字，避免逐章节机械罗列。\n\n"
                f"analysis_material:\n{json.dumps(summary_input, ensure_ascii=False)}"
            ),
        },
    ]
    data = _chat_json(messages, max_tokens=3200)

    return {
        "title": _as_text(data.get("title")) or analysis.get("title", ""),
        "one_sentence_summary": _as_text(data.get("one_sentence_summary")),
        "executive_summary": _as_text(data.get("executive_summary")),
        "research_problem": _as_text(data.get("research_problem")),
        "method_overview": _as_text(data.get("method_overview")),
        "experiment_or_argument_summary": _as_text(data.get("experiment_or_argument_summary")),
        "main_findings": _as_string_list(data.get("main_findings")),
        "limitations": _as_string_list(data.get("limitations")),
        "reproducibility_notes": _as_string_list(data.get("reproducibility_notes")),
        "code_relevance": _as_text(data.get("code_relevance")),
        "report_outline": _as_string_list(data.get("report_outline")),
    }


def answer_question_with_chunks(question: str, chunks: list[dict]) -> dict:
    compact_chunks = [
        {
            "chunk_id": chunk.get("chunk_id", ""),
            "title": chunk.get("title", ""),
            "content": chunk.get("content", ""),
        }
        for chunk in chunks
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是文档问答 agent。你只能基于给定 chunks 回答问题。\n"
                "如果 chunks 中没有答案，请明确说明信息不足。\n"
                "必须只返回 JSON，不要输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请基于 chunks 回答问题，并返回 JSON。\n"
                "JSON 字段必须包含：answer, used_chunks, confidence。\n"
                "used_chunks 是用到的 chunk_id 数组。\n"
                "confidence 只能是 low、medium、high。\n\n"
                f"question: {question}\n\n"
                f"chunks:\n{json.dumps(compact_chunks, ensure_ascii=False)}"
            ),
        },
    ]
    data = _chat_json(messages, max_tokens=2200)
    confidence = _as_text(data.get("confidence")).lower()

    return {
        "answer": _as_text(data.get("answer")),
        "used_chunks": _as_string_list(data.get("used_chunks")),
        "confidence": confidence if confidence in {"low", "medium", "high"} else "low",
    }


def answer_question_with_expanded_context(
    question: str,
    current_chunks: list[dict],
    related_papers: list[dict],
) -> dict:
    current_context = [
        {
            "chunk_id": chunk.get("chunk_id", ""),
            "title": chunk.get("title", ""),
            "content": chunk.get("content", ""),
        }
        for chunk in current_chunks
    ]
    related_context = [
        {
            "paper_id": paper.get("paper_id", ""),
            "title": paper.get("title", ""),
            "score": paper.get("score"),
            "chunks": [
                {
                    "chunk_id": chunk.get("chunk_id", ""),
                    "section_title": chunk.get("section_title", ""),
                    "page_start": chunk.get("page_start"),
                    "content": chunk.get("content", ""),
                }
                for chunk in paper.get("chunks", [])
                if chunk.get("content")
            ],
        }
        for paper in related_papers
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是跨论文问答 agent。你需要优先基于当前论文证据回答问题。\n"
                "如果相关论文证据和问题有关，可以用于补充、对比或扩展。\n"
                "不要把相关论文的内容说成当前论文的内容。\n"
                "如果相关论文证据不足或不相关，请明确说明，不要强行引用。\n"
                "必须只返回 JSON，不要输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请基于 current_paper_chunks 和 related_papers 回答问题，并返回 JSON。\n"
                "JSON 字段必须包含：answer, used_current_chunks, used_related_chunks, confidence。\n"
                "used_current_chunks 和 used_related_chunks 都是 chunk_id 数组。\n"
                "confidence 只能是 low、medium、high。\n\n"
                f"question: {question}\n\n"
                f"current_paper_chunks:\n{json.dumps(current_context, ensure_ascii=False)}\n\n"
                f"related_papers:\n{json.dumps(related_context, ensure_ascii=False)}"
            ),
        },
    ]
    data = _chat_json(messages, max_tokens=2800)
    confidence = _as_text(data.get("confidence")).lower()
    used_current_chunks = _as_string_list(data.get("used_current_chunks"))
    used_related_chunks = _as_string_list(data.get("used_related_chunks"))

    return {
        "answer": _as_text(data.get("answer")),
        "used_chunks": used_current_chunks + used_related_chunks,
        "used_current_chunks": used_current_chunks,
        "used_related_chunks": used_related_chunks,
        "confidence": confidence if confidence in {"low", "medium", "high"} else "low",
    }


def _summarize_section_units(
    section_units: list[dict],
    progress_callback: ProgressCallback | None,
) -> list[dict]:
    if not section_units:
        return []

    skipped_units = [unit for unit in section_units if _should_skip_section_unit(unit)]
    if skipped_units and progress_callback:
        progress_callback(f"跳过 {len(skipped_units)} 个噪声 section")
    section_units = [unit for unit in section_units if not _should_skip_section_unit(unit)]
    if not section_units:
        return []

    max_workers = min(_llm_max_workers(), len(section_units))
    if max_workers <= 1:
        results = []
        for index, unit in enumerate(section_units, start=1):
            if progress_callback:
                progress_callback(f"section agent 开始 {index}/{len(section_units)}：{unit['title']}")
            try:
                results.append(summarize_section_unit(unit))
            except Exception as exc:
                if progress_callback:
                    progress_callback(f"section agent 失败 {index}/{len(section_units)}：{unit['title']}：{exc}")
                raise
            if progress_callback:
                progress_callback(f"section agent 完成 {index}/{len(section_units)}：{unit['title']}")
        return results

    results: list[dict | None] = [None] * len(section_units)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_summarize_section_unit_task, unit, index + 1, len(section_units), progress_callback): index
            for index, unit in enumerate(section_units)
        }
        finished = 0
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                if progress_callback:
                    progress_callback(f"section agent 失败 {finished + 1}/{len(section_units)}：{section_units[index]['title']}：{exc}")
                raise
            finished += 1
            if progress_callback:
                progress_callback(f"section agent 完成 {finished}/{len(section_units)}：{section_units[index]['title']}")

    return [item for item in results if item is not None]


def _summarize_section_unit_task(
    unit: dict,
    index: int,
    total: int,
    progress_callback: ProgressCallback | None,
) -> dict:
    if progress_callback:
        progress_callback(f"section agent 开始 {index}/{total}：{unit['title']}")
    return summarize_section_unit(unit)


def _build_section_units(chunks: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for chunk in sorted(chunks, key=lambda item: item.get("metadata", {}).get("order_index", 0)):
        section_key = _section_key(chunk)
        groups.setdefault(section_key, []).append(chunk)

    units = []
    for section_index, (_, section_chunks) in enumerate(groups.items(), start=1):
        current: list[dict] = []
        part_index = 1

        for chunk in section_chunks:
            candidate = current + [chunk]
            if current and _count_tokens(_unit_content(candidate)) > SECTION_MAX_INPUT_TOKENS:
                units.append(_make_section_unit(f"section_{section_index:03d}_part_{part_index:02d}", current, section_index))
                current = [chunk]
                part_index += 1
            else:
                current = candidate

        if current:
            units.append(_make_section_unit(f"section_{section_index:03d}_part_{part_index:02d}", current, section_index))

    return units


def _make_section_unit(section_id: str, chunks: list[dict], section_index: int) -> dict:
    metadata_list = [chunk.get("metadata", {}) for chunk in chunks]
    first_metadata = metadata_list[0] if metadata_list else {}
    title = _first_text(
        [
            first_metadata.get("section_title"),
            chunks[0].get("title") if chunks else "",
            first_metadata.get("element_type"),
            f"Section {section_index}",
        ]
    )
    hierarchy_path = _first_text([metadata.get("hierarchy_path") for metadata in metadata_list])

    return {
        "section_id": section_id,
        "title": title,
        "hierarchy_path": hierarchy_path,
        "element_types": sorted(
            {
                metadata.get("element_type", "").strip().lower()
                for metadata in metadata_list
                if metadata.get("element_type")
            }
        ),
        "chunk_ids": [chunk.get("chunk_id", "") for chunk in chunks if chunk.get("chunk_id")],
        "page_start": _first_present(chunk.get("page_start") for chunk in chunks),
        "page_end": _last_present(chunk.get("page_end") for chunk in chunks),
        "content": _unit_content(chunks),
    }


def _should_skip_section_unit(unit: dict) -> bool:
    title_text = f"{unit.get('title', '')} {unit.get('hierarchy_path', '')}".strip().lower()
    content_text = unit.get("content", "").lower()
    element_types = {item for item in unit.get("element_types", []) if item}

    if any(marker in content_text for marker in ["authorized licensed use limited to", "restrictions apply"]):
        return True
    if "corresponding author" in content_text or "@126.com" in content_text:
        return True
    if title_text in {"formula", "reference", "references", "biographies"}:
        return True
    if element_types == {"formula"}:
        return True
    return False


def _unit_content(chunks: list[dict]) -> str:
    parts = []
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        parts.append(
            "\n".join(
                [
                    f"chunk_id: {chunk.get('chunk_id', '')}",
                    f"title: {metadata.get('section_title') or chunk.get('title', '')}",
                    f"page: {chunk.get('page_start')}-{chunk.get('page_end')}",
                    f"element_type: {metadata.get('element_type', '')}",
                    "content:",
                    chunk.get("content", ""),
                ]
            )
        )
    return "\n\n---\n\n".join(parts)


def _compact_section_summaries(section_summaries: list[dict]) -> list[dict]:
    return [
        {
            "section_id": item.get("section_id", item.get("chunk_id", "")),
            "title": item.get("title", ""),
            "hierarchy_path": item.get("hierarchy_path", ""),
            "agent_role": item.get("agent_role", ""),
            "summary": _short_text(item.get("summary", ""), 360),
            "key_points": _short_string_list(item.get("key_points", []), 4),
            "methods": _short_string_list(item.get("methods", []), 4),
            "experiments": _short_string_list(item.get("experiments", []), 4),
            "code_hints": _short_string_list(item.get("code_hints", []), 4),
            "open_questions": _short_string_list(item.get("open_questions", []), 4),
        }
        for item in section_summaries
    ]


def _compact_agent_messages(messages: list[dict]) -> list[dict]:
    return [
        {
            "agent": item.get("agent", ""),
            "round": item.get("round"),
            "summary": _short_text(item.get("summary", ""), 260),
            "claims": _short_string_list(item.get("claims", []), 4),
            "disagreements": _short_string_list(item.get("disagreements", []), 4),
            "risks": _short_string_list(item.get("risks", []), 4),
            "code_implications": _short_string_list(item.get("code_implications", []), 4),
            "questions": _short_string_list(item.get("questions", []), 4),
        }
        for item in messages
    ]


def _section_key(chunk: dict) -> str:
    metadata = chunk.get("metadata", {})
    key = _first_text(
        [
            metadata.get("hierarchy_path"),
            metadata.get("section_title"),
            chunk.get("title"),
            metadata.get("element_type"),
            "unknown",
        ]
    )
    return key.strip().lower()


def _agent_role_for_section(title: str, hierarchy_path: str) -> str:
    text = f"{title} {hierarchy_path}".lower()
    if any(keyword in text for keyword in ["method", "approach", "model", "algorithm", "方法", "模型", "算法"]):
        return "method_agent"
    if any(keyword in text for keyword in ["experiment", "evaluation", "dataset", "实验", "评估", "数据集"]):
        return "experiment_agent"
    if any(keyword in text for keyword in ["result", "discussion", "结果", "讨论"]):
        return "result_agent"
    if any(keyword in text for keyword in ["abstract", "introduction", "background", "摘要", "引言", "背景"]):
        return "context_agent"
    if any(keyword in text for keyword in ["conclusion", "future", "结论", "未来"]):
        return "conclusion_agent"
    if any(keyword in text for keyword in ["reference", "bibliography", "参考文献"]):
        return "reference_agent"
    return "general_section_agent"


def _llm_max_workers() -> int:
    return _bounded_int_env("LLM_MAX_WORKERS", DEFAULT_LLM_MAX_WORKERS, 1, 8)


def _agent_max_workers() -> int:
    return _bounded_int_env("AGENT_MAX_WORKERS", DEFAULT_AGENT_MAX_WORKERS, 1, len(DIALOGUE_AGENTS))


def _agent_dialogue_rounds() -> int:
    return _bounded_int_env("AGENT_DIALOGUE_ROUNDS", DEFAULT_AGENT_DIALOGUE_ROUNDS, 0, 4)


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    value = os.getenv(name, str(default))
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(parsed, maximum))


def _chat_json(messages: list[dict], max_tokens: int) -> dict:
    content = chat_completion(messages, max_tokens=max_tokens)
    try:
        return _loads_json(content)
    except RuntimeError as first_error:
        retry_messages = _json_retry_messages(messages, content)
        retry_content = chat_completion(retry_messages, temperature=0, max_tokens=max(max_tokens, 3000))
        try:
            return _loads_json(retry_content)
        except RuntimeError as second_error:
            raise RuntimeError(f"模型返回内容不是有效 JSON，已自动重试一次：{first_error}") from second_error


def _json_retry_messages(messages: list[dict], invalid_content: str) -> list[dict]:
    compact_messages = messages[-2:] if len(messages) >= 2 else messages
    return [
        {
            "role": "system",
            "content": (
                "你必须只返回一个完整 JSON 对象，不要 Markdown，不要解释。"
                "所有数组最多 4 项，每项尽量短。必须闭合所有引号、数组和对象。"
            ),
        },
        *compact_messages,
        {
            "role": "user",
            "content": (
                "上一次输出不是完整 JSON，请基于同一任务重新输出更短的完整 JSON。\n"
                f"invalid_output_prefix:\n{invalid_content[:1200]}"
            ),
        },
    ]


def _loads_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise RuntimeError(f"模型返回内容不是 JSON：{content[:500]}") from exc
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as nested_exc:
            raise RuntimeError(f"模型返回内容不是完整 JSON：{content[:500]}") from nested_exc

    if not isinstance(data, dict):
        raise RuntimeError("模型返回 JSON 不是对象。")
    return data


def _normalize_modules(value: object) -> list[dict]:
    modules = []
    for item in _as_list(value):
        if isinstance(item, dict):
            name = _as_text(item.get("name")) or _as_text(item.get("path"))
            purpose = _as_text(item.get("purpose"))
        else:
            name = _as_text(item)
            purpose = ""

        if not name:
            continue
        modules.append({"name": name, "purpose": purpose or "由多 agent 分析推断"})

    return modules


def _as_string_list(value: object) -> list[str]:
    result = []
    for item in _as_list(value):
        text = _as_text(item)
        if text:
            result.append(text)
    return result


def _short_string_list(value: object, limit: int) -> list[str]:
    return [_short_text(item, 180) for item in _as_string_list(value)[:limit]]


def _short_text(value: object, limit: int) -> str:
    text = _as_text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [value]


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _first_text(values) -> str:
    for value in values:
        text = _as_text(value)
        if text:
            return text
    return ""


def _first_present(values) -> int | None:
    for value in values:
        if value is not None:
            return value
    return None


def _last_present(values) -> int | None:
    result = None
    for value in values:
        if value is not None:
            result = value
    return result


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_chars = len(text) - chinese_chars
    return max(1, int(chinese_chars / 1.8 + other_chars / 4))
