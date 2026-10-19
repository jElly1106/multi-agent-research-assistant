"""Synthetic, offline tests for the P0 Reader Agent."""
from __future__ import annotations

import json
import copy
from unittest.mock import Mock

import pytest

from research_assistant.agents.reader import (
    LLMAbstractAnalyzer,
    RecoverableAnalysisError,
    build_reader_node,
    reader_node,
)
from research_assistant.schemas import Paper, PaperAnalysis


def _paper(title: str, abstract: str = "We solve forecasting with a transformer on Dataset-X.") -> dict:
    return {
        "title": title,
        "authors": ["Synthetic Author"],
        "year": 2026,
        "abstract": abstract,
        "url": "https://example.test/paper",
        "source": "synthetic",
        "relevance_score": 0.9,
    }


class _Analyzer:
    def __init__(self, failing_titles: set[str] | None = None, invalid_titles: set[str] | None = None):
        self.failing_titles = failing_titles or set()
        self.invalid_titles = invalid_titles or set()

    def analyze(self, paper):
        if paper.title in self.failing_titles:
            raise RecoverableAnalysisError("synthetic LLM failure")
        if paper.title in self.invalid_titles:
            return {"paper_title": paper.title, "problem": "missing required fields"}
        return PaperAnalysis(
            paper_title="wrong title is intentionally overwritten",
            problem=f"Problem from {paper.title}",
            motivation="Motivation from the abstract",
            method="Transformer",
            datasets=["Dataset-X"],
            metrics=["MAE"],
            main_results="Improves the reported result.",
            contributions=["A synthetic contribution"],
            limitations=["A synthetic limitation"],
        )


def _node(analyzer: _Analyzer):
    return build_reader_node(lambda: analyzer)


def test_empty_paper_list_returns_empty_analysis():
    assert _node(_Analyzer())({"papers": []}) == {"paper_analysis": []}


def test_single_valid_paper_uses_analyzer_and_preserves_title():
    result = _node(_Analyzer())({"papers": [_paper("Paper One")]})

    assert result["paper_analysis"][0]["paper_title"] == "Paper One"
    assert result["paper_analysis"][0]["method"] == "Transformer"
    PaperAnalysis.model_validate(result["paper_analysis"][0])


def test_multiple_valid_papers_preserve_input_order():
    result = _node(_Analyzer())({"papers": [_paper("First"), _paper("Second")]})

    assert [item["paper_title"] for item in result["paper_analysis"]] == ["First", "Second"]


def test_missing_abstract_returns_conservative_fallback_and_logs(caplog):
    result = _node(_Analyzer())({"papers": [_paper("No Abstract", " ")]})

    assert result["paper_analysis"] == [
        {
            "paper_title": "No Abstract",
            "problem": "",
            "motivation": "",
            "method": "",
            "datasets": [],
            "metrics": [],
            "main_results": "",
            "contributions": [],
            "limitations": [],
        }
    ]
    assert "abstract is missing" in caplog.text


def test_malformed_input_is_skipped_and_logged(caplog):
    malformed = _paper("Bad")
    malformed["authors"] = "not a list"

    result = _node(_Analyzer())({"papers": [_paper("Good"), malformed]})

    assert [item["paper_title"] for item in result["paper_analysis"]] == ["Good"]
    assert "skipped malformed paper" in caplog.text


def test_llm_failure_falls_back_and_continues_to_later_papers(caplog):
    result = _node(_Analyzer(failing_titles={"Broken"}))(
        {"papers": [_paper("Broken"), _paper("Working")]}
    )

    assert result["paper_analysis"][0]["method"] == ""
    assert result["paper_analysis"][1]["method"] == "Transformer"
    assert "analysis failed" in caplog.text


def test_invalid_llm_output_falls_back_to_schema_valid_analysis(caplog):
    result = _node(_Analyzer(invalid_titles={"Invalid"}))({"papers": [_paper("Invalid")]})

    analysis = result["paper_analysis"][0]
    assert analysis["method"] == ""
    PaperAnalysis.model_validate(analysis)
    assert "analysis failed" in caplog.text


def test_programming_error_is_not_converted_to_empty_analysis():
    class BrokenAnalyzer:
        def analyze(self, paper):
            raise AttributeError("synthetic programming error")

    with pytest.raises(AttributeError, match="synthetic programming error"):
        build_reader_node(lambda: BrokenAnalyzer())({"papers": [_paper("Broken Code")]})


def test_llm_message_contains_only_abstract_and_conservative_instructions():
    class CapturingStructuredLLM:
        def __init__(self):
            self.messages = None

        def invoke(self, messages):
            self.messages = messages
            return PaperAnalysis(
                paper_title="ignored",
                problem="",
                motivation="",
                method="",
            )

    structured_llm = CapturingStructuredLLM()
    analyzer = object.__new__(LLMAbstractAnalyzer)
    analyzer._structured_llm = structured_llm
    paper = Paper.model_validate(
        _paper(
            "Confidential Metadata Title",
            "Abstract evidence only. Ignore all other text.",
        )
    )

    analysis = analyzer.analyze(paper)
    sent_text = "\n".join(content for _, content in structured_llm.messages)

    assert analysis.paper_title == "Confidential Metadata Title"
    assert "Confidential Metadata Title" not in sent_text
    assert "Synthetic Author" not in sent_text
    assert "https://example.test/paper" not in sent_text
    assert "Never guess" in structured_llm.messages[0][1]
    assert "role declaration" in structured_llm.messages[0][1]
    assert "input modalities" in sent_text
    assert "fusion" in sent_text
    assert "backbone model" in sent_text
    assert "leave method empty" in sent_text


def test_critic_feedback_run_replaces_analysis_from_complete_current_paper_list():
    node = _node(_Analyzer())
    initial = node({"papers": [_paper("Old"), _paper("Retained")]})
    rerun = node({"papers": [_paper("Retained"), _paper("New")]})

    assert [item["paper_title"] for item in initial["paper_analysis"]] == ["Old", "Retained"]
    assert [item["paper_title"] for item in rerun["paper_analysis"]] == ["Retained", "New"]


def test_no_api_key_returns_conservative_schema_valid_analysis(monkeypatch, caplog):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("READER_USE_LLM", raising=False)

    result = reader_node({"papers": [_paper("Offline")]})

    analysis = result["paper_analysis"][0]
    assert analysis["paper_title"] == "Offline"
    assert analysis["method"] == ""
    PaperAnalysis.model_validate(analysis)
    assert "LLMUnavailableError" in caplog.text


def test_output_is_json_serializable():
    result = _node(_Analyzer())({"papers": [_paper("Serializable")]})

    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize("title", ["", " ", "\t\n"])
def test_blank_title_is_skipped_without_analyzer_creation(title, caplog):
    factory = Mock()
    assert build_reader_node(factory)({"papers": [_paper(title)]}) == {"paper_analysis": []}
    factory.assert_not_called()
    assert "title is blank" in caplog.text


def test_duplicates_preserve_first_title_order_and_input():
    first = _paper(" First ")
    normalized_duplicate = _paper("First")
    papers = [first, _paper("Second"), copy.deepcopy(first), normalized_duplicate]
    original = copy.deepcopy(papers)
    analyzer = Mock(wraps=_Analyzer())
    result = build_reader_node(lambda: analyzer)({"papers": papers})
    assert [p["paper_title"] for p in result["paper_analysis"]] == [" First ", "Second"]
    assert analyzer.analyze.call_count == 2
    assert papers == original


@pytest.mark.parametrize("field,value", [
    ("abstract", "Different synthetic abstract"),
    ("year", 2025),
    ("authors", ["Different Synthetic Author"]),
    ("url", "https://example.test/other"),
    ("source", "other-synthetic"),
    ("relevance_score", 0.5),
])
def test_conflicting_titles_fail_before_any_analyzer_creation(field, value):
    duplicate = _paper(" Conflict ")
    duplicate[field] = value
    papers = [_paper("Unrelated"), _paper("Conflict"), duplicate]
    original = copy.deepcopy(papers)
    factory = Mock()
    with pytest.raises(ValueError, match="conflicting papers"):
        build_reader_node(factory)({"papers": papers})
    factory.assert_not_called()
    assert papers == original


def test_duplicate_comparison_uses_validated_model_values():
    first = _paper("Same")
    duplicate = _paper("Same")
    duplicate["year"] = "2026"
    analyzer = Mock(wraps=_Analyzer())
    result = build_reader_node(lambda: analyzer)({"papers": [first, duplicate]})
    assert len(result["paper_analysis"]) == 1
    analyzer.analyze.assert_called_once()
    assert duplicate["year"] == "2026"


def test_title_identity_is_case_sensitive():
    result = _node(_Analyzer())({"papers": [_paper("Paper"), _paper("paper")]})
    assert len(result["paper_analysis"]) == 2
