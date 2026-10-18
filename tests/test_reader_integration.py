"""Offline graph-level integration test using the production Reader node."""
from __future__ import annotations

from research_assistant.agents.reader import reader_node
from research_assistant.demo_stubs import demo_critic_node, demo_writer_node
from research_assistant.graph import build_research_graph
from research_assistant.schemas import PaperAnalysis


def _paper(title: str) -> dict:
    return {
        "title": title,
        "authors": ["Synthetic Author"],
        "year": 2026,
        "abstract": "Synthetic abstract for offline graph integration.",
        "url": "https://example.test/paper",
        "source": "synthetic",
        "relevance_score": 0.9,
    }


def test_production_reader_transfers_complete_search_results_to_analyst(monkeypatch):
    monkeypatch.setenv("COORDINATOR_USE_LLM", "0")
    monkeypatch.setenv("READER_USE_LLM", "0")
    papers = [_paper("First Search Result"), _paper("Second Search Result")]
    observed: dict[str, object] = {}

    def search_node(state):
        return {"papers": papers}

    def analyst_node(state):
        analyses = state["paper_analysis"]
        observed["analysis"] = analyses
        for analysis in analyses:
            PaperAnalysis.model_validate(analysis)
        return {"method_summary": {"summary": "Analyst received Reader output"}}

    graph = build_research_graph(
        search_node=search_node,
        reader_node=reader_node,
        analyst_node=analyst_node,
        critic_node=demo_critic_node,
        writer_node=demo_writer_node,
    )
    result = graph.invoke({"topic": "offline Reader integration"})

    assert [item["paper_title"] for item in result["paper_analysis"]] == [
        "First Search Result",
        "Second Search Result",
    ]
    assert observed["analysis"] == result["paper_analysis"]
    assert result["method_summary"]["summary"] == "Analyst received Reader output"


def test_reader_replaces_complete_analysis_in_feedback_graph(monkeypatch):
    """Synthetic Search/Analyst/Critic/Writer; actual Reader, no network."""
    monkeypatch.setenv("COORDINATOR_USE_LLM", "0")
    monkeypatch.setenv("READER_USE_LLM", "0")
    observed = []
    search_calls = []

    def search(state):
        search_calls.append(state.get("critic_result", {}))
        titles = ["Synthetic Old", "Synthetic Retained"] if len(search_calls) == 1 else [
            "Synthetic Retained", "Synthetic New"
        ]
        return {"papers": [_paper(title) for title in titles]}

    def analyst(state):
        for item in state["paper_analysis"]:
            PaperAnalysis.model_validate(item)
            assert item["method"] == ""
        titles = [item["paper_title"] for item in state["paper_analysis"]]
        observed.append(titles)
        return {"method_summary": {"summary": ", ".join(titles)}}

    def critic(state):
        return {"critic_result": {
            "decision": "FAIL" if len(observed) == 1 else "PASS",
            "new_search_queries": ["synthetic supplementary query"],
        }}

    graph = build_research_graph(
        search_node=search, reader_node=reader_node, analyst_node=analyst,
        critic_node=critic,
        writer_node=lambda state: {"final_report": state["method_summary"]["summary"]},
    )
    result = graph.invoke({"topic": "Synthetic feedback", "max_critic_rounds": 2})
    assert observed == [
        ["Synthetic Old", "Synthetic Retained"],
        ["Synthetic Retained", "Synthetic New"],
    ]
    assert search_calls[1]["new_search_queries"] == ["synthetic supplementary query"]
    assert result["critic_round"] == 2
    assert result["critic_result"]["decision"] == "PASS"
    assert result["final_report"] == "Synthetic Retained, Synthetic New"
