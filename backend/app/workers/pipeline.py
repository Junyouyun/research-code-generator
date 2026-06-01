import json
from pathlib import Path
from time import perf_counter
from typing import Callable, TypeVar

from app.config import ARTIFACT_DIR, GENERATED_DIR, PARSED_DIR
from app.core.database import (
    add_project_event,
    get_project,
    list_document_chunks,
    save_document_chunks,
    update_project_status,
)
from app.core.models import ProjectStatus
from app.services.artifact_builder import build_artifact
from app.services.code_generator import generate_code_files
from app.services.code_planner import plan_code_project
from app.services.code_repairer import validate_and_repair_code
from app.services.code_runner import CodeValidationError
from app.services.document_chunker import chunk_document_elements
from app.services.document_loader import elements_to_parsed_paper, load_document_elements
from app.services.experiment_spec_builder import build_experiment_spec
from app.services.llm_paper_analyzer import analyze_paper_with_llm
from app.services.project_memory import (
    record_analysis_memory,
    record_code_plan_memory,
    record_experiment_spec_memory,
    record_validation_memory,
)
from app.services.report_generator import generate_report


T = TypeVar("T")


def run_project_pipeline(project_id: str, document_path: Path) -> None:
    try:
        parsed_dir = PARSED_DIR / project_id
        generated_dir = GENERATED_DIR / project_id
        code_dir = generated_dir / "code"
        artifact_path = ARTIFACT_DIR / project_id / "result.zip"

        parsed_dir.mkdir(parents=True, exist_ok=True)
        generated_dir.mkdir(parents=True, exist_ok=True)

        add_project_event(project_id, "pipeline", "任务开始")
        _add_thought_event(
            project_id,
            "pipeline",
            "已接收文档，准备进入分析流程",
            "我会先把文档变成统一结构，再切分语义 chunks，最后交给 LLM 和多 agent 做总结。",
            [
                "确认上传文件已经进入项目目录",
                "准备抽取正文、标题、表格、公式等文档元素",
                "后续报告和代码都会基于数据库中的 chunks 生成",
            ],
            ["文档解析", "chunks", "LLM 分析"],
        )

        def parse_document() -> tuple[list[dict], dict]:
            elements = load_document_elements(document_path, project_id)
            _write_json(parsed_dir / "elements.json", elements)

            parsed_paper = elements_to_parsed_paper(elements, str(document_path))
            _write_json(parsed_dir / "paper.json", parsed_paper)
            add_project_event(project_id, "parsing_document", f"解析得到 {len(elements)} 个文档元素")
            _add_thought_event(
                project_id,
                "parsing_document",
                "正在把原始文档转成统一元素列表",
                f"已得到 {len(elements)} 个 DocumentElement，后续会基于这些元素重建阅读顺序和章节结构。",
                [
                    "把不同来源的内容统一成标题、段落、表格、公式、图片等元素",
                    "保留页码、层级、元素类型等元数据",
                    "为后续语义切分提供稳定输入",
                ],
                [f"{len(elements)} elements", "DocumentElement", "阅读顺序"],
            )
            return elements, parsed_paper

        def build_chunks() -> list[dict]:
            chunks = chunk_document_elements(elements)
            _write_json(parsed_dir / "chunks.json", chunks)
            add_project_event(project_id, "chunking", f"生成 {len(chunks)} 个语义 chunks")
            _add_thought_event(
                project_id,
                "chunking",
                "正在按章节和语义边界生成 chunks",
                f"已生成 {len(chunks)} 个语义 chunks，会尽量保持上下文连续，而不是简单按页切开。",
                [
                    "优先按标题层级和段落边界组织内容",
                    "对过长内容做稳定切分，避免超过模型输入窗口",
                    "保留 chunk 与原始文档位置的关联",
                ],
                [f"{len(chunks)} chunks", "语义切分", "上下文连续"],
            )
            return chunks

        def save_chunks() -> list[dict]:
            save_document_chunks(project_id, chunks)
            db_chunks = list_document_chunks(project_id)
            add_project_event(project_id, "saving_chunks", f"入库 {len(db_chunks)} 个 chunks")
            _add_thought_event(
                project_id,
                "saving_chunks",
                "正在把 chunks 保存到 SQLite",
                f"已入库 {len(db_chunks)} 个 chunks，后续总结、问答和检索都从数据库读取。",
                [
                    "把 chunk 内容和元数据写入 document_chunks 表",
                    "后续问答会根据问题从这些 chunks 中取证据",
                    "避免每次问答都重新解析原始文档",
                ],
                [f"{len(db_chunks)} chunks", "SQLite", "检索基础"],
            )
            return db_chunks

        def index_vectors() -> dict:
            from app.services.vector_store import index_document_chunks

            result = index_document_chunks(project_id, db_chunks)
            indexed_count = result.get("indexed", 0)
            collection = result.get("collection", "")
            embedding_model = result.get("embedding_model", "")
            add_project_event(
                project_id,
                "indexing_vectors",
                f"向量索引写入 {indexed_count} 个 chunks",
                details={
                    "collection": collection,
                    "embedding_model": embedding_model,
                    "indexed": indexed_count,
                    "vector_store": "qdrant",
                },
            )
            _add_thought_event(
                project_id,
                "indexing_vectors",
                "正在为 chunks 建立向量索引",
                f"已将 {indexed_count} 个 chunks 写入 Qdrant，后续问答会先检索相关 chunks，再交给 LLM 生成回答。",
                [
                    "使用 embedding 模型把 chunk 文本转成向量",
                    "向量 payload 保留 project_id、paper_id、paper_version_id 和 chunk_id",
                    "同步写入 vector_index_records，便于后续 reindex 和排查",
                ],
                [f"{indexed_count} vectors", "Qdrant", embedding_model or "embedding"],
            )
            return result

        def summarize_chunks() -> tuple[dict, list[dict]]:
            analysis, section_summaries = analyze_paper_with_llm(
                parsed_paper,
                db_chunks,
                progress_callback=lambda message: _add_llm_progress_event(project_id, message),
            )
            _write_json(parsed_dir / "analysis.json", analysis)
            _record_memory_safely(
                project_id,
                lambda: record_analysis_memory(project_id, analysis),
                "analysis_memory",
            )
            add_project_event(project_id, "summarizing_chunks", f"完成 {len(section_summaries)} 个 section agent 分析")
            _add_thought_event(
                project_id,
                "summarizing_chunks",
                "已完成章节分析和最终总结",
                f"共完成 {len(section_summaries)} 个 section agent 分析，并生成最终报告所需的结构化结论。",
                [
                    "先让 section agent 分析不同标题下的内容",
                    "再让多 agent 从方法、实验、代码和风险角度交叉检查",
                    "最后汇总成 final_summary，供报告生成器使用",
                ],
                [f"{len(section_summaries)} sections", "多 agent", "final_summary"],
            )
            return analysis, section_summaries

        def build_report() -> str:
            report = generate_report(analysis)
            (generated_dir / "report.md").write_text(report, encoding="utf-8")
            _add_thought_event(
                project_id,
                "building_report",
                "正在生成最终研究报告",
                "报告会优先使用 final_summary，把章节分析和多 agent 评审压缩成用户可读的结果。",
                [
                    "提取研究问题、方法、结论和局限",
                    "把结构化分析转成 Markdown 报告",
                    "避免把中间调试信息直接暴露给用户",
                ],
                ["report.md", "final_summary", "Markdown"],
            )
            return report

        def build_code_plan() -> dict:
            graph_context = _get_code_generation_graph_context(project_id)
            _write_json(generated_dir / "graph_context.json", graph_context)
            experiment_spec = build_experiment_spec(analysis, db_chunks, graph_context)
            _write_json(generated_dir / "experiment_spec.json", experiment_spec)
            _record_memory_safely(
                project_id,
                lambda: record_experiment_spec_memory(project_id, experiment_spec),
                "experiment_spec_memory",
            )
            add_project_event(
                project_id,
                ProjectStatus.PLANNING_CODE.value,
                "Experiment spec built",
                details={
                    "experiment_type": experiment_spec.get("experiment_type", ""),
                    "project_type": experiment_spec.get("project_type", ""),
                    "domain": experiment_spec.get("domain", ""),
                },
            )
            code_plan = plan_code_project(analysis, db_chunks, experiment_spec, graph_context)
            _record_memory_safely(
                project_id,
                lambda: record_code_plan_memory(project_id, code_plan),
                "code_plan_memory",
            )
            _write_json(generated_dir / "code_spec.json", code_plan)
            _write_json(generated_dir / "code_plan.json", code_plan)
            _add_thought_event(
                project_id,
                "planning_code",
                "正在规划最小可运行代码",
                "代码部分会保持少文件、单入口，尽量准确表达论文中明确给出的可复现部分。",
                [
                    "判断论文更适合 analysis_tool、data_pipeline 还是 algorithm_scaffold",
                    "只保留 main.py、requirements.txt、README 等必要文件",
                    "论文没写清楚的算法细节不会强行伪造",
                ],
                ["main.py", "少文件", "可运行入口"],
            )
            return code_plan

        def validate_code() -> dict:
            def emit_repair_event(event: dict) -> None:
                event_name = event.get("event", "")
                is_error = event_name in {"validation_failed", "repair_exhausted"}
                kind = "code_repair" if "repair" in event_name else "code_validation"
                add_project_event(
                    project_id,
                    ProjectStatus.CHECKING_CODE.value,
                    event.get("message", "Generated code validation event"),
                    level="error" if is_error else "info",
                    details={
                        "kind": kind,
                        "event": event_name,
                        "attempt": event.get("attempt"),
                        "changed_files": event.get("changed_files", []),
                        "diagnostics": event.get("diagnostics", []),
                        "commands": event.get("commands", []),
                    },
                )

            try:
                return validate_and_repair_code(
                    code_dir,
                    code_plan,
                    analysis,
                    db_chunks,
                    event_callback=emit_repair_event,
                )
            except CodeValidationError as exc:
                add_project_event(
                    project_id,
                    ProjectStatus.CHECKING_CODE.value,
                    exc.result.get("message", "Generated code validation failed"),
                    level="error",
                    details={
                        "kind": "code_validation",
                        "success": False,
                        "repairs": exc.result.get("repairs", []),
                        "diagnostics": exc.result.get("diagnostics", []),
                        "commands": exc.result.get("commands", []),
                    },
                )
                raise

        elements, parsed_paper = _run_step(
            project_id,
            ProjectStatus.PARSING_DOCUMENT,
            "解析文档",
            15,
            parse_document,
        )
        chunks = _run_step(project_id, ProjectStatus.CHUNKING, "生成语义 chunks", 28, build_chunks)
        db_chunks = _run_step(project_id, ProjectStatus.SAVING_CHUNKS, "保存 chunks 到数据库", 35, save_chunks)
        _run_step(
            project_id,
            ProjectStatus.INDEXING_VECTORS,
            "建立向量索引",
            43,
            index_vectors,
        )
        analysis, _ = _run_step(
            project_id,
            ProjectStatus.SUMMARIZING_CHUNKS,
            "LLM 总结与结构化分析",
            55,
            summarize_chunks,
        )
        _build_knowledge_graph_safely(project_id, analysis, db_chunks)
        _run_step(project_id, ProjectStatus.BUILDING_REPORT, "生成研究报告", 68, build_report)
        code_plan = _run_step(project_id, ProjectStatus.PLANNING_CODE, "规划代码结构", 76, build_code_plan)
        _run_step(
            project_id,
            ProjectStatus.GENERATING_CODE,
            "生成代码文件",
            88,
            lambda: generate_code_files(code_plan, code_dir, analysis, db_chunks, graph_context=code_plan.get("graph_context", {})),
        )
        validation_result = _run_step(
            project_id,
            ProjectStatus.CHECKING_CODE,
            "检查生成代码可运行性",
            92,
            validate_code,
        )
        add_project_event(
            project_id,
            ProjectStatus.CHECKING_CODE.value,
            validation_result.get("message", "Generated code validation passed"),
            details={
                "kind": "code_validation",
                "success": validation_result.get("success", False),
                "repairs": validation_result.get("repairs", []),
                "diagnostics": validation_result.get("diagnostics", []),
                "commands": validation_result.get("commands", []),
            },
        )
        _record_memory_safely(
            project_id,
            lambda: record_validation_memory(project_id, validation_result),
            "validation_memory",
        )
        _run_step(
            project_id,
            ProjectStatus.PACKAGING,
            "打包产物",
            96,
            lambda: build_artifact(generated_dir, artifact_path),
        )

        update_project_status(project_id, ProjectStatus.COMPLETED, "completed", 100)
        add_project_event(project_id, "pipeline", "任务完成")
    except Exception as exc:
        update_project_status(project_id, ProjectStatus.FAILED, "failed", 100, str(exc))
        add_project_event(project_id, "pipeline", f"任务失败：{exc}", level="error")
        raise


def _build_knowledge_graph_safely(project_id: str, analysis: dict, chunks: list[dict]) -> None:
    project = get_project(project_id)
    if project is None:
        return

    add_project_event(project_id, "knowledge_graph", "开始：抽取论文知识图谱")
    try:
        from app.services.knowledge_graph_store import build_and_save_project_graph

        result = build_and_save_project_graph(project, analysis, chunks)
        add_project_event(
            project_id,
            "knowledge_graph",
            f"完成：抽取 {result.get('entity_count', 0)} 个实体、{result.get('relation_count', 0)} 条关系",
            details={
                "kind": "knowledge_graph",
                "entity_count": result.get("entity_count", 0),
                "relation_count": result.get("relation_count", 0),
                "selected_chunk_ids": result.get("selected_chunk_ids", []),
            },
        )
    except Exception as exc:
        try:
            from app.services.knowledge_graph_store import record_project_graph_failure

            record_project_graph_failure(project, str(exc))
        except Exception:
            pass
        add_project_event(
            project_id,
            "knowledge_graph",
            f"知识图谱抽取失败，已跳过：{exc}",
            level="warning",
            details={"kind": "knowledge_graph", "error": str(exc)},
        )


def _get_code_generation_graph_context(project_id: str) -> dict:
    try:
        project = get_project(project_id)
        if project is None:
            return {"entities": [], "relations": [], "paths": []}

        from app.services.knowledge_graph_store import get_code_generation_graph_context

        return get_code_generation_graph_context(project)
    except Exception as exc:
        add_project_event(
            project_id,
            "knowledge_graph",
            f"代码生成图谱上下文读取失败：{exc}",
            level="warning",
            details={"kind": "knowledge_graph", "stage": "code_generation_context"},
        )
        return {"entities": [], "relations": [], "paths": []}


def _record_memory_safely(project_id: str, action: Callable[[], None], label: str) -> None:
    try:
        action()
    except Exception as exc:
        add_project_event(
            project_id,
            "project_memory",
            f"Project memory write skipped during {label}: {exc}",
            level="warning",
        )


def _run_step(
    project_id: str,
    status: ProjectStatus,
    current_step: str,
    progress: int,
    action: Callable[[], T],
) -> T:
    update_project_status(project_id, status, current_step, progress)
    add_project_event(project_id, status.value, f"开始：{current_step}")
    started_at = perf_counter()

    try:
        result = action()
    except Exception as exc:
        duration_ms = int((perf_counter() - started_at) * 1000)
        add_project_event(
            project_id,
            status.value,
            f"失败：{current_step}，{exc}",
            level="error",
            duration_ms=duration_ms,
        )
        raise

    duration_ms = int((perf_counter() - started_at) * 1000)
    add_project_event(project_id, status.value, f"完成：{current_step}", duration_ms=duration_ms)
    return result


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _add_llm_progress_event(project_id: str, message: str) -> None:
    add_project_event(
        project_id,
        "summarizing_chunks",
        message,
        details=_thought_details_from_progress_message(message),
    )


def _thought_details_from_progress_message(message: str) -> dict | None:
    if "prepare_sections" in message:
        return _thought_details(
            "正在重建论文的章节结构",
            "我会先把数据库中的 chunks 按标题和层级整理成 section，后面每个 section 会交给独立 agent 分析。",
            [
                "读取 chunk 的标题、层级路径和元素类型",
                "合并属于同一标题下的相邻 chunks",
                "为后续并发 section agent 准备任务列表",
            ],
            ["prepare_sections", "章节重建", "LangGraph"],
        )

    if "summarize_sections" in message or "section agent" in message:
        return _thought_details(
            "正在并发分析不同章节",
            "每个 section agent 负责一个标题下的内容，完成后会汇总成章节级摘要。",
            [
                "过滤纯公式、页脚、授权信息等噪声 section",
                "限制每个 section 的输入长度，避免模型请求过慢",
                "保留每个章节的核心观点、方法线索和可复现信息",
            ],
            ["section agent", "并发分析", "章节摘要"],
        )

    if "agent_dialogue" in message or "agent" in message and "round" in message:
        return _thought_details(
            "正在进行多 agent 交叉检查",
            "不同角色会从方法、实验、代码复现和风险角度互相补充，减少单次总结遗漏。",
            [
                "方法 agent 关注研究方法是否清楚",
                "代码 agent 关注哪些内容能转成可运行代码",
                "批判 agent 关注证据不足、局限和复现风险",
            ],
            ["多 agent", "交叉检查", "复现风险"],
        )

    if "global_analysis" in message:
        return _thought_details(
            "正在生成全局结构化分析",
            "我会把章节摘要和多 agent 讨论压缩成统一 analysis，供报告和代码规划使用。",
            [
                "合并研究问题、方法、结论和局限",
                "提取可复现模块和所需输入",
                "把中间讨论结果整理成稳定字段",
            ],
            ["global_analysis", "结构化分析", "代码规划依据"],
        )

    if "final_summary" in message:
        return _thought_details(
            "正在生成最终可读总结",
            "我会把 analysis、section summaries 和 agent dialogue 再压缩成一份更适合展示的 final_summary。",
            [
                "减少重复的中间分析内容",
                "突出研究问题、方法、主要结论和局限",
                "让最终报告优先使用更自然的总结结果",
            ],
            ["final_summary", "最终报告", "信息压缩"],
        )

    return None


def _add_thought_event(
    project_id: str,
    step: str,
    title: str,
    summary: str,
    bullets: list[str],
    tags: list[str],
) -> None:
    add_project_event(
        project_id,
        step,
        title,
        details=_thought_details(title, summary, bullets, tags),
    )


def _thought_details(title: str, summary: str, bullets: list[str], tags: list[str]) -> dict:
    return {
        "kind": "thought",
        "title": title,
        "summary": summary,
        "bullets": bullets[:3],
        "tags": tags[:6],
    }
