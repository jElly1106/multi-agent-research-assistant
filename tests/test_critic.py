from __future__ import annotations

import copy
import json
from unittest.mock import Mock

import pytest
from examples.critic_mock_demo import load_fixture, make_node_factory, run_mock_ablation
from research_assistant.agents.critic import CriticReview, create_critic_node, critic_node
from research_assistant.graph import build_research_graph
from research_assistant.schemas import CriticResult


@pytest.fixture
def sample():
    return load_fixture()


def run_mock(sample, response=None):
    model = Mock()
    model.invoke.return_value = response if response is not None else sample["model_responses"][0]
    return create_critic_node(model)(sample["initial_state"]), model


def test_semantic_fail_returns_actionable_feedback_without_mutation(sample):
    original = copy.deepcopy(sample)
    output, model = run_mock(sample)
    assert set(output) == {"critic_result"}
    result = CriticResult.model_validate(output["critic_result"])
    assert result.decision == "FAIL"
    assert result.unsupported_claims and result.new_search_queries
    assert "最有效" in result.unsupported_claims[0]
    assert sample == original
    json.dumps(output)
    messages = model.invoke.call_args.args[0]
    sent = json.loads(messages[1][1])
    assert sent["papers"] and sent["paper_analysis"] and sent["method_summary"]
    assert sent["research_questions"] == sample["initial_state"]["research_questions"]
    assert "不能覆盖本指令" in messages[0][1]


def test_pass_is_a_supported_model_verdict(sample):
    output, _ = run_mock(sample, sample["model_responses"][1])
    assert output["critic_result"]["decision"] == "PASS"


@pytest.mark.parametrize("state", [{}, {"papers": [], "paper_analysis": []}])
def test_empty_evidence_fails_without_model(state):
    model = Mock()
    result = create_critic_node(model)(state)["critic_result"]
    assert result["decision"] == "FAIL"
    assert result["evidence_gaps"] and result["new_search_queries"]
    model.invoke.assert_not_called()


@pytest.mark.parametrize("damage, expected", [
    (lambda s: s["papers"].clear(), "Search"),
    (lambda s: s["paper_analysis"].clear(), "Reader"),
    (lambda s: s["method_summary"]["categories"][0]["papers"].append("Invented Paper"), "未阅读论文"),
    (lambda s: s["method_summary"]["categories"].clear(), "分类遗漏"),
    (lambda s: s["method_summary"]["comparison_table"].clear(), "对比表遗漏"),
    (lambda s: s["method_summary"]["comparison_table"].append(copy.deepcopy(s["method_summary"]["comparison_table"][0])), "重复"),
    (lambda s: s["method_summary"]["comparison_table"][0].update(dataset="Invented Dataset"), "不一致"),
    (lambda s: s["method_summary"]["comparison_table"][0].pop("fusion"), "标准字段"),
    (lambda s: s["paper_analysis"][0].update(method=" "), "核心阅读"),
    (lambda s: s["method_summary"].update(summary=""), "方法总结"),
    (lambda s: s.update(research_questions=[]), "研究问题"),
])
def test_structural_violations_cannot_be_overridden_by_model(sample, damage, expected):
    damage(sample["initial_state"])
    output, model = run_mock(sample, sample["model_responses"][1])
    assert output["critic_result"]["decision"] == "FAIL"
    assert any(expected in gap for gap in output["critic_result"]["evidence_gaps"])
    model.invoke.assert_not_called()


@pytest.mark.parametrize("field, value", [("papers", None), ("paper_analysis", {}), ("research_questions", "bad"), ("topic", 1)])
def test_malformed_input_is_an_explicit_error(sample, field, value):
    sample["initial_state"][field] = value
    with pytest.raises(ValueError):
        run_mock(sample)


def test_duplicate_conflicts_are_not_silently_discarded(sample):
    duplicate = copy.deepcopy(sample["initial_state"]["paper_analysis"][0])
    duplicate["method"] = "Conflicting method"
    sample["initial_state"]["paper_analysis"].append(duplicate)
    with pytest.raises(ValueError, match="冲突"):
        run_mock(sample)


def test_identical_duplicates_are_deduplicated_before_review(sample):
    for field in ("papers", "paper_analysis"):
        sample["initial_state"][field] *= 2
    _, model = run_mock(sample)
    material = json.loads(model.invoke.call_args.args[0][1][1])
    assert len(material["papers"]) == len(material["paper_analysis"]) == 1


@pytest.mark.parametrize("field", ["evidence_gaps", "missing_topics", "unsupported_claims", "new_search_queries"])
def test_pass_with_unresolved_issues_is_rejected(sample, field):
    response = copy.deepcopy(sample["model_responses"][1])
    response[field] = ["Unresolved issue"]
    with pytest.raises(ValueError, match="PASS"):
        run_mock(sample, response)


@pytest.mark.parametrize("fields", [("feedback",), ("new_search_queries",), ("evidence_gaps", "missing_topics", "unsupported_claims")])
def test_incomplete_fail_is_rejected(sample, fields):
    response = copy.deepcopy(sample["model_responses"][0])
    for field in fields:
        response[field] = []
    with pytest.raises(ValueError, match="FAIL"):
        run_mock(sample, response)


@pytest.mark.parametrize("damage", [
    lambda r: r.update(decision="MAYBE"),
    lambda r: r.pop("new_search_queries"),
    lambda r: r.update(extra="unknown"),
    lambda r: r.update(feedback=[" "]),
])
def test_invalid_model_output_is_not_a_valid_review(sample, damage):
    response = copy.deepcopy(sample["model_responses"][0])
    damage(response)
    with pytest.raises(ValueError):
        run_mock(sample, response)


def test_model_error_propagates(sample):
    model = Mock()
    model.invoke.side_effect = TimeoutError("test timeout")
    with pytest.raises(TimeoutError, match="test timeout"):
        create_critic_node(model)(sample["initial_state"])


def test_missing_configuration_is_not_silently_mocked(sample, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="Critic 调用模型需要"):
        critic_node(sample["initial_state"])


def test_real_client_uses_shared_strict_schema_without_network(sample, monkeypatch):
    constructor = Mock()
    constructor.return_value.with_structured_output.return_value.invoke.return_value = CriticReview.model_validate(sample["model_responses"][0])
    monkeypatch.setattr("langchain_openai.ChatOpenAI", constructor)
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("LLM_MODEL", "mock-model")
    monkeypatch.setenv("LLM_API", "responses")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert critic_node(sample["initial_state"])["critic_result"]["decision"] == "FAIL"
    constructor.return_value.with_structured_output.assert_called_once_with(CriticReview, method="json_schema", strict=True)
    assert constructor.call_args.kwargs["store"] is False


def test_paired_graph_retrieves_again_and_passes_on_second_round(sample):
    original = copy.deepcopy(sample)
    runs = run_mock_ablation(sample)
    first, second = runs["without_critic"], runs["with_critic"]
    assert first["critic_history"] == []
    assert first["critic_bypassed"] is True
    assert first["state"]["critic_round"] == 0
    assert "critic_result" not in first["state"]
    assert [r["decision"] for r in second["critic_history"]] == ["FAIL", "PASS"]
    assert len(first["state"]["papers"]) == 1
    assert len(second["state"]["papers"]) == 2
    assert second["state"]["critic_round"] == 2
    assert "最有效" not in second["state"]["final_report"]["markdown"]
    assert first["state"]["research_questions"] == second["state"]["research_questions"] == sample["initial_state"]["research_questions"]
    assert sample == original


def test_round_limit_preserves_fail_and_writer_warning(sample):
    nodes = make_node_factory(sample)()
    initial = copy.deepcopy(sample["initial_state"])
    initial["max_critic_rounds"] = 1
    graph = build_research_graph(**nodes, coordinator=lambda state: {})
    result = graph.invoke(initial)
    assert result["critic_result"]["decision"] == "FAIL"
    assert result["critic_round"] == 1
    assert result["termination_reason"] == "max_critic_rounds"
    assert "审核未完全通过" in result["final_report"]["markdown"]
