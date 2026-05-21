from typing import Callable, TypedDict

from langgraph.graph import END, StateGraph

from app.services.llm_paper_analyzer import (
    _build_section_units,
    _summarize_section_units,
    build_final_summary,
    build_global_analysis,
    run_agent_dialogue,
)


ProgressCallback = Callable[[str], None]


class AnalysisGraphState(TypedDict, total=False):
    parsed_paper: dict
    chunks: list[dict]
    section_units: list[dict]
    section_summaries: list[dict]
    agent_dialogue: dict
    analysis: dict
    final_summary: dict
    progress_callback: ProgressCallback | None


def run_llm_analysis_graph(
    parsed_paper: dict,
    chunks: list[dict],
    progress_callback: ProgressCallback | None = None,
) -> tuple[dict, list[dict]]:
    graph = _build_graph()
    final_state = graph.invoke(
        {
            "parsed_paper": parsed_paper,
            "chunks": chunks,
            "progress_callback": progress_callback,
        }
    )
    return final_state["analysis"], final_state["section_summaries"]


def _build_graph():
    workflow = StateGraph(AnalysisGraphState)

    workflow.add_node("prepare_sections", _prepare_sections)
    workflow.add_node("summarize_sections", _summarize_sections)
    workflow.add_node("agent_dialogue", _agent_dialogue)
    workflow.add_node("global_analysis", _global_analysis)
    workflow.add_node("final_summary", _final_summary)

    workflow.set_entry_point("prepare_sections")
    workflow.add_edge("prepare_sections", "summarize_sections")
    workflow.add_edge("summarize_sections", "agent_dialogue")
    workflow.add_edge("agent_dialogue", "global_analysis")
    workflow.add_edge("global_analysis", "final_summary")
    workflow.add_edge("final_summary", END)

    return workflow.compile()


def _prepare_sections(state: AnalysisGraphState) -> AnalysisGraphState:
    _emit(state, "LangGraph 节点开始：prepare_sections")
    section_units = _build_section_units(state["chunks"])
    _emit(state, f"LangGraph 节点完成：prepare_sections，得到 {len(section_units)} 个 section")
    return {"section_units": section_units}


def _summarize_sections(state: AnalysisGraphState) -> AnalysisGraphState:
    section_units = state["section_units"]
    _emit(state, "LangGraph 节点开始：summarize_sections")
    _emit(state, f"按标题分成 {len(section_units)} 个 section agent 任务")
    section_summaries = _summarize_section_units(section_units, state.get("progress_callback"))
    _emit(state, f"LangGraph 节点完成：summarize_sections，完成 {len(section_summaries)} 个 section agent")
    return {"section_summaries": section_summaries}


def _agent_dialogue(state: AnalysisGraphState) -> AnalysisGraphState:
    _emit(state, "LangGraph 节点开始：agent_dialogue")
    agent_dialogue = run_agent_dialogue(state["section_summaries"], state.get("progress_callback"))
    _emit(state, "LangGraph 节点完成：agent_dialogue")
    return {"agent_dialogue": agent_dialogue}


def _global_analysis(state: AnalysisGraphState) -> AnalysisGraphState:
    _emit(state, "LangGraph 节点开始：global_analysis")
    analysis = build_global_analysis(
        state["parsed_paper"],
        state["section_summaries"],
        state.get("agent_dialogue"),
    )
    _emit(state, "LangGraph 节点完成：global_analysis")
    return {"analysis": analysis}


def _final_summary(state: AnalysisGraphState) -> AnalysisGraphState:
    _emit(state, "LangGraph 节点开始：final_summary")
    final_summary = build_final_summary(
        state["analysis"],
        state["section_summaries"],
        state.get("agent_dialogue", {}),
    )
    analysis = dict(state["analysis"])
    agent_dialogue = analysis.pop("agent_dialogue", state.get("agent_dialogue", {}))
    analysis["final_summary"] = final_summary
    analysis["debug"] = {
        "section_summaries": state["section_summaries"],
        "agent_dialogue": agent_dialogue,
    }
    _emit(state, "LangGraph 节点完成：final_summary")
    return {"analysis": analysis, "final_summary": final_summary}


def _emit(state: AnalysisGraphState, message: str) -> None:
    callback = state.get("progress_callback")
    if callback:
        callback(message)
