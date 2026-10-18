from __future__ import annotations

import copy

import pytest

from examples.critic_ablation_demo import mock_annotations
from examples.critic_mock_demo import load_fixture, run_mock_ablation
from research_assistant.evaluation import compare_runs, evaluate_run


@pytest.fixture
def state():
    return {
        "papers": [
            {"title": "Paper A", "authors": ["A"], "source": "test"},
            {"title": " paper  a ", "authors": ["A"], "source": "test"},
            {"title": "Paper B", "authors": ["B"], "source": "test"},
        ],
        "research_questions": ["Question 1", "Question 2"],
        "final_report": {"title": "Report", "markdown": "Answer one. Answer two.", "references": ["Paper A", "Unknown Paper"]},
        "critic_round": 2,
    }


def test_metrics_have_explicit_denominators_and_do_not_mutate(state):
    original = copy.deepcopy(state)
    labels = {
        "papers": [
            {"title": "Paper A", "is_real": True, "is_valid": True, "note": "Independent verification A"},
            {"title": "Paper B", "is_real": False, "is_valid": False, "note": "Independent verification B"},
        ],
        "citations": [
            {"reference": "Paper A", "correct": True, "note": "Evidence supports the claim"},
            {"reference": "Unknown Paper", "correct": False, "note": "Cannot verify reference"},
        ],
        "questions": [
            {"question": "Question 1", "covered": True, "evidence": "Answer one."},
            {"question": "Question 2", "covered": False},
        ],
    }
    metrics = evaluate_run(state, labels, critic_history=[{"decision": "FAIL"}, {"decision": "PASS"}])
    assert metrics["paper_count"] == 3
    assert metrics["unique_paper_count"] == 2
    assert metrics["duplicate_rate"] == pytest.approx(1 / 3)
    assert metrics["verified_real_paper_count"] == 1
    assert metrics["invalid_paper_ratio"] == 0.5
    assert metrics["reference_traceability_rate"] == metrics["citation_correctness_rate"] == 0.5
    assert metrics["report_coverage_rate"] == 0.5
    assert metrics["critic_invocations"] == 2
    assert metrics["critic_fail_count"] == 1
    assert state == original


def test_no_annotations_does_not_claim_fact_checking_or_coverage(state):
    metrics = evaluate_run(state)
    assert metrics["invalid_paper_ratio"] is None
    assert metrics["citation_correctness_rate"] is None
    assert metrics["report_coverage_rate"] is None
    assert metrics["validity_judgment_coverage"] == 0
    assert metrics["critic_fail_count"] is None


def test_partial_annotations_report_their_coverage(state):
    metrics = evaluate_run(state, {"papers": [{"title": "Paper A", "is_valid": True, "note": "verified"}],
                                   "questions": [{"question": "Question 1", "covered": True, "evidence": "Answer one."}]})
    assert metrics["invalid_paper_ratio"] == 0
    assert metrics["validity_judgment_coverage"] == 0.5
    assert metrics["report_coverage_rate"] is None
    assert metrics["question_judgment_coverage"] == 0.5


def test_empty_inputs_have_undefined_ratios_and_zero_counts():
    metrics = evaluate_run({}, critic_history=[])
    assert metrics["paper_count"] == metrics["critic_invocations"] == metrics["critic_fail_count"] == 0
    for key in ("duplicate_rate", "invalid_paper_ratio", "reference_traceability_rate", "citation_correctness_rate", "report_coverage_rate"):
        assert metrics[key] is None


@pytest.mark.parametrize("labels", [
    {"papers": [{"title": "Wrong", "is_real": True, "note": "checked"}]},
    {"papers": [{"title": "Paper A", "is_real": True}]},
    {"papers": [{"title": "Paper A", "is_real": False, "is_valid": True, "note": "contradiction"}]},
    {"papers": [{"title": "Paper A"}, {"title": "paper a"}]},
    {"citations": [{"reference": "Paper B", "correct": True, "note": "not in report"}]},
    {"questions": [{"question": "Question 1", "covered": True, "evidence": "Invented excerpt"}]},
    {"questions": [{"question": "Question 1", "covered": True}]},
])
def test_untraceable_or_inconsistent_annotations_are_rejected(state, labels):
    with pytest.raises(ValueError):
        evaluate_run(state, labels)


def test_conflicting_duplicate_metadata_needs_resolution(state):
    state["papers"][1]["source"] = "different"
    with pytest.raises(ValueError, match="冲突"):
        evaluate_run(state)


def test_string_report_does_not_guess_references(state):
    state["final_report"] = "Report mentions Paper A"
    assert evaluate_run(state)["reference_traceability_rate"] is None


def test_ablation_metrics_show_only_scripted_improvement():
    fixture = load_fixture()
    runs = run_mock_ablation(fixture)
    metrics = {arm: evaluate_run(run["state"], mock_annotations(fixture, arm), critic_history=run["critic_history"])
               for arm, run in runs.items()}
    comparison = compare_runs(metrics["without_critic"], metrics["with_critic"])
    assert comparison["without_critic"]["critic_invocations"] == 0
    assert comparison["with_critic"]["critic_invocations"] == 2
    assert comparison["delta_with_minus_without"]["report_coverage_rate"] == 0.5
    # 模拟论文始终不真实；补充模拟论文不能提高真实性与真实引用正确率。
    assert comparison["with_critic"]["verified_real_paper_count"] == 0
    assert comparison["with_critic"]["citation_correctness_rate"] == 0
    assert comparison["with_critic"]["invalid_paper_ratio"] == 1


def test_unknown_metrics_are_not_subtracted_as_zero():
    result = compare_runs({"unknown": None, "rate": 0.25}, {"unknown": 1, "rate": 0.75})
    assert result["delta_with_minus_without"] == {"rate": 0.5}


def test_partial_critic_history_is_rejected(state):
    with pytest.raises(ValueError, match="完整历史"):
        evaluate_run(state, critic_history=[{"decision": "PASS"}])


@pytest.mark.parametrize("bad_state", [[], None, {"papers": None}])
def test_malformed_state_is_an_explicit_error(bad_state):
    with pytest.raises(ValueError):
        evaluate_run(bad_state)
