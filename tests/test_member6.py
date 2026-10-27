"""Offline orchestration checks with synthetic nodes and recorded responses."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from research_assistant.agents.writer import create_writer_node
from research_assistant.graph import build_research_graph
from research_assistant.member6 import NODES, build_app, stream_research
from research_assistant.member6_cli import main


def test_demo_never_uses_configured_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("LLM_MODEL", "synthetic-model")
    reject = Mock(side_effect=AssertionError("Demo attempted model API"))
    monkeypatch.setattr("research_assistant.llm.create_structured_model", reject)
    monkeypatch.setattr("research_assistant.agents.writer.create_structured_model", reject)
    monkeypatch.setattr("research_assistant.agents.analyst._create_model", reject)
    events = list(stream_research("合成主题"))
    assert tuple(e["node"] for e in events) == NODES
    report = events[-1]["state"]["final_report"]
    assert len(report["references"]) == 3
    assert "演示材料" in report["markdown"] and "MOCK" in report["markdown"]
    assert "方法比较" in report["markdown"]
    reject.assert_not_called()


@pytest.mark.parametrize("decision", ["PASS", "FAIL"])
def test_real_writer_after_feedback_loop_and_round_limit(decision):
    def search(state):
        return {"papers": [{"title": "SYNTHETIC A", "authors": [], "source": "synthetic"}]}
    def critic(state):
        return {"critic_result": {"decision": "FAIL" if state.get("critic_round", 0) == 0 else decision,
                                  "feedback": ["synthetic gap"], "new_search_queries": ["synthetic query"]}}
    graph = build_research_graph(coordinator=lambda s: {"research_questions": ["合成问题"]},
                                search_node=search, reader_node=lambda s: {"paper_analysis": []},
                                analyst_node=lambda s: {"method_summary": {}}, critic_node=critic,
                                writer_node=create_writer_node(use_llm=False))
    events = list(stream_research("synthetic", graph=graph))
    assert [e["node"] for e in events].count("search") == 2
    state = events[-1]["state"]
    assert state["critic_round"] == 2 and state["critic_result"]["decision"] == decision
    assert ("审核未完全通过" in state["final_report"]["markdown"]) == (decision == "FAIL")


def test_live_checks_keys_and_switches_before_network(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_app(mode="live")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setenv("LLM_MODEL", "synthetic")
    monkeypatch.setenv("READER_USE_LLM", "0")
    with pytest.raises(RuntimeError, match="开关"):
        build_app(mode="live")


def test_live_wiring_runs_actual_nodes_with_synthetic_model_and_provider(monkeypatch):
    """Official-shaped URL is synthetic validation input, never a real paper."""
    from research_assistant.agents.reader import build_reader_node
    from research_assistant.agents.analyst import create_analyst_node
    from research_assistant.agents.critic import create_critic_node
    from research_assistant.agents.search import create_search_node
    from research_assistant.schemas import Paper, CoordinatorOutput
    from research_assistant.search.models import ProviderResult, SearchHit
    import research_assistant.member6 as service
    title = "MOCK_ONLY synthetic integration paper"
    question = "What does the synthetic method do?"
    paper = Paper(title=title, authors=["Synthetic Author"], year=2026,
                  abstract="Synthetic method and evidence for integration only.", source="crossref",
                  url="https://doi.org/10.1234/synthetic-test-only")
    class Provider:
        name = "crossref"
        def search(self, query, *, limit):
            return ProviderResult(hits=[SearchHit(paper=paper, source_id="synthetic-test-only")])
    class Analyzer:
        def analyze(self, paper):
            return {"paper_title": title, "problem": "Synthetic problem", "motivation": "Synthetic motivation",
                    "method": "Synthetic method", "datasets": [], "metrics": [], "limitations": []}
    analyst = Mock(invoke=Mock(return_value={
        "categories": [{"name": "Synthetic", "description": "Synthetic", "papers": [title]}],
        "comparison_table": [{"paper": title, "input": "Synthetic", "fusion": "Synthetic", "backbone": "Synthetic"}],
        "findings": [{"text": "Synthetic method only", "papers": [title]}], "evolution": [], "evidence_gaps": []}))
    critic = Mock(invoke=Mock(return_value={"decision": "PASS", "feedback": [], "evidence_gaps": [],
                                          "missing_topics": [], "unsupported_claims": [], "new_search_queries": []}))
    writer = Mock(invoke=Mock(return_value={"background": [], "answers": [{"question": question,
        "statements": [{"text": "Synthetic method only", "papers": [title]}], "evidence_gap": ""}], "directions": []}))
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("LLM_MODEL", "synthetic-model")
    monkeypatch.setenv("READER_USE_LLM", "1")
    monkeypatch.setenv("COORDINATOR_USE_LLM", "1")
    monkeypatch.setattr("research_assistant.agents.coordinator._invoke_llm", lambda topic: CoordinatorOutput(
        research_scope="Synthetic integration only", research_questions=[question], search_keywords=["synthetic"],
        search_directions=[], research_plan=["synthetic"]))
    monkeypatch.setattr("research_assistant.agents.search.create_search_node", lambda **kwargs:
                        create_search_node(config=kwargs["config"], providers=[Provider()]))
    monkeypatch.setattr("research_assistant.agents.reader.reader_node", build_reader_node(Analyzer))
    monkeypatch.setattr("research_assistant.agents.analyst.analyst_node", create_analyst_node(analyst))
    monkeypatch.setattr("research_assistant.agents.critic.critic_node", create_critic_node(critic))
    monkeypatch.setattr(service, "create_writer_node", lambda: create_writer_node(writer))
    events = list(service.stream_research("synthetic", mode="live", sources=("crossref",)))
    assert tuple(e["node"] for e in events) == NODES
    assert events[-1]["state"]["final_report"]["references"] == [title]
    for model in (analyst, critic, writer):
        model.invoke.assert_called_once()


@pytest.mark.parametrize("topic,rounds", [(" ", 2), ("synthetic", 0), ("synthetic", 6), ("synthetic", True)])
def test_invalid_run_inputs(topic, rounds):
    with pytest.raises(ValueError):
        list(stream_research(topic, max_critic_rounds=rounds))


def test_cli_demo_exports_and_refuses_overwrite(tmp_path, monkeypatch):
    output = tmp_path/"delivery"
    assert main(["synthetic", "--output-dir", str(output)]) == 0
    state = json.loads((output/"state.json").read_text("utf-8"))
    assert len(state["final_report"]["references"]) == 3
    original = (output/"report.md").read_bytes()
    assert main(["another", "--output-dir", str(output)]) == 1
    assert (output/"report.md").read_bytes() == original


def test_ui_demo_pdf_and_failure_clears_old_report(monkeypatch):
    pytest.importorskip("streamlit")
    pytest.importorskip("reportlab")
    from streamlit.testing.v1 import AppTest
    import research_assistant.member6 as service
    app = AppTest.from_file(str(Path(__file__).parents[1]/"app.py"), default_timeout=30).run()
    assert not app.exception
    next(b for b in app.button if b.label == "开始研究").click().run()
    assert not app.exception
    assert "final_report" in app.session_state["result"]
    next(b for b in app.button if b.label == "准备 PDF").click().run()
    assert not app.exception and app.session_state["pdf"].startswith(b"%PDF")
    monkeypatch.setattr(service, "stream_research", Mock(side_effect=TimeoutError("secret must not appear")))
    next(b for b in app.button if b.label == "开始研究").click().run()
    assert not app.exception
    assert app.session_state["failed"] is True
    assert "result" not in app.session_state
    assert "secret must not appear" not in " ".join(e.value for e in app.error)
