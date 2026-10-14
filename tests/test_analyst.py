from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from research_assistant.agents.analyst import (
    AnalystOutput,
    MISSING,
    analyst_node,
    create_analyst_node,
)
from research_assistant.graph import build_research_graph
from research_assistant.schemas import ResearchLandscape


@pytest.fixture
def sample():
    return json.loads(
        (Path(__file__).parents[1] / "examples" / "fixtures" / "analyst_mock.json")
        .read_text(encoding="utf-8")
    )


def run_mock(sample):
    model = Mock()
    model.invoke.return_value = sample["model_response"]
    return create_analyst_node(model)(sample["state"]), model


def test_structured_analysis_preserves_interface_and_evidence(sample):
    original = copy.deepcopy(sample["state"])
    result, model = run_mock(sample)
    assert set(result) == {"method_summary"}
    landscape = ResearchLandscape.model_validate(result["method_summary"])
    assert len(landscape.categories) == 3
    assert len(landscape.comparison_table) == 3
    assert landscape.comparison_table[0]["fusion"] == "早期特征拼接"
    assert landscape.comparison_table[1]["dataset"] == "MOCK_DATASET_B"
    assert landscape.comparison_table[1]["limitation"] == "尚未测试文本缺失场景"
    assert "不能支持性能优劣排名" in landscape.summary
    assert "依据：MOCK_ONLY" in landscape.summary
    assert all("依据：MOCK_ONLY" in step for step in landscape.evolution)
    assert sample["state"] == original
    json.dumps(result, ensure_ascii=False)
    model.invoke.assert_called_once()


def test_prompt_contains_current_evidence_and_critic_feedback_only(sample):
    sample["state"]["critic_result"] = {"feedback": ["重新比较融合机制"]}
    sample["state"]["method_summary"] = {"summary": "过时的结论"}
    _, model = run_mock(sample)
    messages = model.invoke.call_args.args[0]
    material = json.loads(messages[1][1])
    assert material["paper_analysis"] == sample["state"]["paper_analysis"]
    assert material["research_questions"] == sample["state"]["research_questions"]
    assert material["critic_feedback"] == sample["state"]["critic_result"]
    assert "method_summary" not in material


@pytest.mark.parametrize("state", [{}, {"paper_analysis": []}])
def test_empty_input_does_not_call_model(state):
    model = Mock()
    result = create_analyst_node(model)(state)["method_summary"]
    assert result["categories"] == result["comparison_table"] == result["evolution"] == []
    assert "证据不足" in result["summary"]
    model.invoke.assert_not_called()


def test_missing_fields_stay_unknown(sample):
    result, _ = run_mock(sample)
    row = result["method_summary"]["comparison_table"][2]
    assert row["backbone"] == row["dataset"] == row["limitation"] == MISSING
    assert "未提供数据集" in result["method_summary"]["summary"]
    assert "未提供局限" in result["method_summary"]["summary"]


def test_identical_duplicates_are_removed_before_model_call(sample):
    sample["state"]["paper_analysis"].append(copy.deepcopy(sample["state"]["paper_analysis"][0]))
    _, model = run_mock(sample)
    assert len(json.loads(model.invoke.call_args.args[0][1][1])["paper_analysis"]) == 3


def test_conflicting_duplicate_is_rejected_before_model_call(sample):
    duplicate = copy.deepcopy(sample["state"]["paper_analysis"][0])
    duplicate["method"] = "冲突的方法"
    sample["state"]["paper_analysis"].append(duplicate)
    model = Mock()
    with pytest.raises(ValueError, match="阅读结果冲突"):
        create_analyst_node(model)(sample["state"])
    model.invoke.assert_not_called()


def test_reader_papers_must_match_search_when_metadata_is_supplied(sample):
    sample["state"]["papers"].pop()
    with pytest.raises(ValueError, match="未出现在 Search"):
        run_mock(sample)


@pytest.mark.parametrize("field", ["categories", "comparison_table", "findings", "evolution"])
def test_unknown_model_citations_are_rejected(sample, field):
    row = sample["model_response"][field][0]
    if field == "comparison_table":
        row["paper"] = "Invented Paper"
    else:
        row["papers"] = ["Invented Paper"]
    with pytest.raises(ValueError, match="输入之外"):
        run_mock(sample)


@pytest.mark.parametrize("field", ["categories", "comparison_table"])
def test_omitted_papers_are_rejected(sample, field):
    sample["model_response"][field].pop()
    with pytest.raises(ValueError, match="遗漏"):
        run_mock(sample)


def test_duplicate_comparison_rows_are_rejected(sample):
    sample["model_response"]["comparison_table"].append(sample["model_response"]["comparison_table"][0])
    with pytest.raises(ValueError, match="不重复"):
        run_mock(sample)


def test_unreferenced_finding_is_rejected(sample):
    sample["model_response"]["findings"][0]["papers"] = []
    with pytest.raises(ValidationError):
        run_mock(sample)


def test_missing_years_do_not_allow_timeline(sample):
    del sample["state"]["papers"]
    with pytest.raises(ValueError, match="缺少年份"):
        run_mock(sample)


def test_metadata_is_optional_for_non_temporal_analysis(sample):
    del sample["state"]["papers"]
    sample["model_response"]["evolution"] = []
    result, _ = run_mock(sample)
    assert result["method_summary"]["evolution"] == []
    assert "未形成可验证的技术演进路线" in result["method_summary"]["summary"]


@pytest.mark.parametrize("bad_input", [None, {}, "invalid"])
def test_invalid_input_container_is_rejected(sample, bad_input):
    sample["state"]["paper_analysis"] = bad_input
    with pytest.raises(ValueError, match="必须是列表"):
        run_mock(sample)


def test_incomplete_reader_record_is_rejected(sample):
    del sample["state"]["paper_analysis"][0]["method"]
    with pytest.raises(ValidationError):
        run_mock(sample)


def test_missing_model_config_is_explicit(sample, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="需要 OPENAI_API_KEY 和 LLM_MODEL"):
        analyst_node(sample["state"])


def test_real_client_configuration_without_network(sample, monkeypatch):
    constructor = Mock()
    structured = constructor.return_value.with_structured_output.return_value
    structured.invoke.return_value = AnalystOutput.model_validate(sample["model_response"])
    monkeypatch.setattr("langchain_openai.ChatOpenAI", constructor)
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("LLM_MODEL", "mock-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://mock.invalid/v1")
    result = analyst_node(sample["state"])
    assert result["method_summary"]["categories"]
    assert constructor.call_args.kwargs["model"] == "mock-model"
    assert constructor.call_args.kwargs["base_url"] == "https://mock.invalid/v1"
    constructor.return_value.with_structured_output.assert_called_once_with(
        AnalystOutput, method="json_schema", strict=True
    )


def test_model_failure_is_not_replaced_with_fabricated_analysis(sample):
    model = Mock()
    model.invoke.side_effect = TimeoutError("mock timeout")
    with pytest.raises(TimeoutError, match="mock timeout"):
        create_analyst_node(model)(sample["state"])


def test_invented_dataset_field_in_model_output_is_rejected(sample):
    sample["model_response"]["comparison_table"][0]["dataset"] = "Invented Dataset"
    with pytest.raises(ValidationError):
        run_mock(sample)


def test_graph_reanalyzes_all_papers_after_critic_feedback(sample, monkeypatch):
    monkeypatch.setenv("COORDINATOR_USE_LLM", "0")
    first_output = copy.deepcopy(sample["model_response"])
    for field in ["categories", "comparison_table", "evolution"]:
        first_output[field] = first_output[field][:2]
    first_output["findings"] = [first_output["findings"][1]]
    first_output["evidence_gaps"] = ["MOCK_ONLY：需补充表示对齐路线"]
    model = Mock()
    model.invoke.side_effect = [first_output, sample["model_response"]]
    search_calls = []

    def search(state):
        search_calls.append(copy.deepcopy(state))
        count = 2 if len(search_calls) == 1 else 3
        return {"papers": sample["state"]["papers"][:count]}

    def reader(state):
        titles = {p["title"] for p in state["papers"]}
        return {"paper_analysis": [p for p in sample["state"]["paper_analysis"] if p["paper_title"] in titles]}

    def critic(state):
        if len(state["method_summary"]["comparison_table"]) == 2:
            return {"critic_result": {"decision": "FAIL", "new_search_queries": ["mock contrastive alignment"]}}
        return {"critic_result": {"decision": "PASS"}}

    graph = build_research_graph(
        search_node=search,
        reader_node=reader,
        analyst_node=create_analyst_node(model),
        critic_node=critic,
        writer_node=lambda state: {"final_report": state["method_summary"]["summary"]},
    )
    result = graph.invoke({"topic": "Mock Research", "critic_round": 0, "max_critic_rounds": 2})
    assert result["critic_round"] == 2
    assert result["critic_result"]["decision"] == "PASS"
    assert len(result["method_summary"]["comparison_table"]) == 3
    assert len(result["method_summary"]["categories"]) == 3
    assert "MOCK_ONLY C" in result["final_report"]
    assert search_calls[1]["critic_result"]["new_search_queries"] == ["mock contrastive alignment"]
    assert model.invoke.call_count == 2
    second_material = json.loads(model.invoke.call_args.args[0][1][1])
    assert len(second_material["paper_analysis"]) == 3
    assert second_material["critic_feedback"]["decision"] == "FAIL"
