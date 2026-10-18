"""Synthetic independent pipeline and admission-budget tests; no network."""
import base64
import copy
import json
from unittest.mock import Mock

import pytest

from research_assistant.agents.reader import LLMAbstractAnalyzer, RecoverableAnalysisError, empty_analysis
from research_assistant.reader_budget import BudgetExceeded, ReaderBudget, local_bpe_counter
from research_assistant.reader_pipeline import run_reader
from research_assistant.schemas import PaperAnalysis


def paper(title="Synthetic"):
    return {"title": title, "authors": [], "source": "synthetic", "abstract": "Synthetic abstract"}


class SyntheticAbstract:
    def analyze(self, paper):
        return empty_analysis(paper).model_copy(update={"method": "Synthetic abstract method"})


class SyntheticFulltext:
    def analyze(self, chunk):
        return {"claims": [{"field": "method", "value": "Synthetic method A", "quote": "Synthetic method A"}]}


def test_pipeline_real_pdf_and_input_immutability(tmp_path):
    from test_reader_pdf import make_pdf
    path = tmp_path / "synthetic.pdf"
    make_pdf(path, texts=("Synthetic method A",))
    papers = [paper(), paper("Missing")]
    paths = {"Synthetic": path}
    original = copy.deepcopy((papers, paths))
    result = run_reader(papers, paths, abstract_analyzer_factory=SyntheticAbstract,
                        fulltext_analyzer_factory=SyntheticFulltext)
    assert [p["method"] for p in result["paper_analysis"]] == ["Synthetic method A", "Synthetic abstract method"]
    assert result["details"][0]["field_sources"]["method"] == "fulltext"
    assert result["details"][1]["field_sources"]["method"] == "abstract"
    assert result["budget"]["admitted_calls"] == 3
    assert (papers, paths) == original
    assert json.loads(json.dumps(result)) == result


def test_batch_call_limit_continues_with_empty_fallback():
    result = run_reader([paper("First"), paper("Second")],
        abstract_analyzer_factory=SyntheticAbstract, budget_options={"max_calls": 1})
    assert result["paper_analysis"][0]["method"] == "Synthetic abstract method"
    assert result["paper_analysis"][1]["method"] == ""
    assert result["budget"]["admitted_calls"] == 1
    assert result["budget"]["events"][-1]["code"] == "call_budget_exceeded"


def test_budget_counts_prompt_schema_and_output_reserve():
    captured = []
    def counter(text):
        captured.append(json.loads(text))
        return 10
    budget = ReaderBudget(token_counter=counter, context_tokens=100, output_tokens=20,
                          overhead_tokens=5, max_reserved_tokens=35)
    budget.reserve(stage="synthetic", title="Synthetic", messages=[("system", "rules"), ("human", "evidence")], schema=PaperAnalysis)
    assert captured[0]["messages"][0] == ["system", "rules"]
    assert "properties" in captured[0]["schema"]
    assert budget.reserved == 35
    with pytest.raises(BudgetExceeded, match="batch_token_budget"):
        budget.reserve(stage="synthetic", title="Synthetic", messages=[], schema=PaperAnalysis)
    assert budget.calls == 1


def test_context_denial_prevents_analyzer_construction():
    factory = Mock()
    result = run_reader([paper()], abstract_analyzer_factory=factory,
        budget_options={"token_counter": lambda text: 20_000})
    factory.assert_not_called()
    assert result["budget"]["admitted_calls"] == 0
    assert result["budget"]["events"][0]["code"] == "context_budget_exceeded"


def test_failed_calls_remain_reserved_and_programming_errors_propagate():
    analyzer = Mock()
    analyzer.analyze.side_effect = RecoverableAnalysisError("synthetic failure")
    result = run_reader([paper()], abstract_analyzer_factory=lambda: analyzer)
    assert result["budget"]["admitted_calls"] == 1
    assert result["budget"]["reserved_tokens"] > 0
    analyzer.analyze.side_effect = AttributeError("synthetic bug")
    with pytest.raises(AttributeError):
        run_reader([paper()], abstract_analyzer_factory=lambda: analyzer)


def test_disabled_no_model_construction_and_full_replacement(monkeypatch):
    monkeypatch.setenv("READER_USE_LLM", "0")
    first = run_reader([paper()])
    assert first["budget"]["admitted_calls"] == 0
    assert first["paper_analysis"][0]["method"] == ""
    assert run_reader([])["paper_analysis"] == []


def test_validation_precedes_calls():
    factory = Mock()
    for kwargs in [{"pdf_paths": {"": "bad.pdf"}}, {"fulltext_options": {"max_chunks": 0}},
                   {"budget_options": {"output_tokens": 0}}, {"budget_options": []},
                   {"fulltext_options": {"abstract_analyses": []}}]:
        with pytest.raises(ValueError):
            run_reader([paper()], abstract_analyzer_factory=factory, **kwargs)
    factory.assert_not_called()


def test_fulltext_context_budget_preserves_abstract(tmp_path):
    from test_reader_pdf import make_pdf
    path = tmp_path / "synthetic.pdf"
    make_pdf(path, texts=("Synthetic method A",))
    factory = Mock()
    def counter(text):
        return 50_000 if '"claims"' in text else 10
    result = run_reader([paper()], {"Synthetic": path},
        abstract_analyzer_factory=SyntheticAbstract, fulltext_analyzer_factory=factory,
        budget_options={"token_counter": counter})
    factory.assert_not_called()
    assert result["paper_analysis"][0]["method"] == "Synthetic abstract method"
    assert result["budget"]["events"][-1]["code"] == "context_budget_exceeded"


def test_default_adapters_enforce_output_and_no_retries(monkeypatch):
    monkeypatch.setenv("READER_USE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("LLM_MODEL", "synthetic-model")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API", raising=False)
    constructor = Mock()
    constructor.return_value.with_structured_output.return_value.invoke.return_value = {
        "paper_title": "Synthetic", "problem": "", "motivation": "", "method": ""}
    monkeypatch.setattr("langchain_openai.ChatOpenAI", constructor)
    result = run_reader([paper()], budget_options={"output_tokens": 256})
    assert constructor.call_args.kwargs["max_tokens"] == 256
    assert constructor.call_args.kwargs["max_retries"] == 0
    assert result["budget"]["admitted_calls"] == 1


def test_local_tokenizer_file_only(tmp_path):
    # Synthetic byte vocabulary, not a tokenizer for any production model.
    ranks = tmp_path / "synthetic.tiktoken"
    ranks.write_text("\n".join(f"{base64.b64encode(bytes([i])).decode()} {i}" for i in range(256)), encoding="ascii")
    count = local_bpe_counter(ranks, pattern=r"[\s\S]")
    assert count("中A") == 4
    with pytest.raises(ValueError):
        local_bpe_counter(tmp_path / "missing", pattern=".")


@pytest.mark.parametrize("options", [{"max_calls": False}, {"token_counter": 3},
                                   {"context_tokens": 10}, {"overhead_tokens": 0}])
def test_invalid_budget(options):
    with pytest.raises(ValueError):
        ReaderBudget(**options)
