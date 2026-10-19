"""Synthetic evidence coordination; no real papers or model services."""
from unittest.mock import Mock

import pytest

from research_assistant.agents.reader import RecoverableAnalysisError, empty_analysis
from research_assistant.reader_fulltext import LLMReconciler, analyze_fulltext_materials
from research_assistant.schemas import Paper
from test_reader_fulltext import paper, material, claim


def run(decisions, *, fail=None):
    abstract = empty_analysis(Paper.model_validate(paper())).model_dump()
    abstract["method"] = "Synthetic abstract fallback"
    extractor = Mock()
    extractor.analyze.side_effect = [
        {"claims": [claim("method", "A", "method A")]},
        {"claims": [claim("method", "B", "Dataset-X"), claim("datasets", "X", "Dataset-X")]},
    ]
    resolver = Mock()
    resolver.analyze.return_value = {"fields": decisions}
    resolver.analyze.side_effect = fail
    result = analyze_fulltext_materials([paper()], [material()],
        abstract_analyses=[abstract], analyzer_factory=lambda: extractor,
        reconcile=True, reconciler_factory=lambda: resolver)
    return result, resolver


def decision(mode, indices, field="method"):
    return {"field": field, "decision": mode, "indices": indices}


@pytest.mark.parametrize("mode,indices,expected", [
    ("compatible", [1, 0], "A；B"), ("select", [1], "B"),
    ("abstain", [], "Synthetic abstract fallback")])
def test_source_only_selection_and_abstention(mode, indices, expected):
    result, resolver = run([decision(mode, indices)])
    assert result["paper_analysis"][0]["method"] == expected
    assert result["paper_analysis"][0]["datasets"] == ["X"]
    detail = result["details"][0]
    assert len(detail["evidence"]) == 3  # Rejected candidates remain auditable.
    candidates = resolver.analyze.call_args.args[0]
    assert candidates["method"][0]["value"] == "A"
    assert candidates["method"][0]["evidence"][0]["page"] == 1
    assert detail["reconciliation"]["status"] == "ok"
    if mode == "abstain":
        assert detail["field_sources"]["method"] == "abstract"
        assert detail["status"] == "partial"


@pytest.mark.parametrize("decisions", [
    [], [decision("select", [99])], [decision("select", [True])],
    [decision("select", ["1"])], [decision("select", [])],
    [decision("select", [0, 1])], [decision("compatible", [0])],
    [decision("compatible", [0, 0, 1])], [decision("abstain", [0])],
    [decision("select", [0]), decision("select", [1])],
    [decision("select", [0], "problem")],
])
def test_invalid_decisions_fall_back_without_losing_other_fields(decisions):
    result, _ = run(decisions)
    assert result["paper_analysis"][0]["method"] == "Synthetic abstract fallback"
    assert result["paper_analysis"][0]["datasets"] == ["X"]
    assert {i["code"] for i in result["details"][0]["issues"]} == {"reconciliation_failed"}


def test_resolver_failure_and_programming_error_boundaries():
    result, _ = run([], fail=RecoverableAnalysisError("synthetic failure"))
    assert result["paper_analysis"][0]["method"] == "Synthetic abstract fallback"
    for error in [AttributeError("synthetic bug"), ValueError("synthetic adapter bug")]:
        with pytest.raises(type(error), match="synthetic"):
            run([], fail=error)


def test_no_coordination_for_single_value_or_disabled_mode():
    resolver = Mock(side_effect=AssertionError("unexpected resolver"))
    extractor = Mock()
    extractor.analyze.return_value = {"claims": [claim("method", "A", "method A")]}
    for enabled in [False, True]:
        analyze_fulltext_materials([paper()], [material(("Synthetic method A",))],
            analyzer_factory=lambda: extractor, reconcile=enabled, reconciler_factory=resolver)
    resolver.assert_not_called()


def test_resolver_adapter_only_accepts_decisions():
    adapter = object.__new__(LLMReconciler)
    adapter.model = Mock()
    adapter.model.invoke.return_value = {"fields": [decision("abstain", [])]}
    assert adapter.analyze({"method": []}).fields[0].decision == "abstain"
    adapter.model.invoke.return_value = {"fields": [dict(decision("select", [0]), value="invented")]}
    with pytest.raises(RecoverableAnalysisError):
        adapter.analyze({"method": []})


def test_pipeline_budget_denial_prevents_coordination(tmp_path):
    from test_reader_pdf import make_pdf
    from test_reader_pipeline import SyntheticAbstract
    from research_assistant.reader_pipeline import run_reader
    path = tmp_path / "synthetic.pdf"
    make_pdf(path, texts=("Synthetic method A", "Synthetic method B"))
    class Extractor:
        def analyze(self, chunk):
            return {"claims": [claim("method", chunk["text"], chunk["text"])]}
    resolver = Mock()
    result = run_reader([{**paper(), "abstract": "Synthetic abstract"}], {"Synthetic": path},
        abstract_analyzer_factory=SyntheticAbstract, fulltext_analyzer_factory=Extractor,
        reconciler_factory=resolver, fulltext_options={"reconcile": True},
        budget_options={"max_calls": 3})
    resolver.assert_not_called()
    assert result["budget"]["events"][-1]["stage"] == "reconciliation"
    assert result["budget"]["events"][-1]["code"] == "call_budget_exceeded"
    assert result["paper_analysis"][0]["method"] == "Synthetic abstract method"


def test_pipeline_coordination_is_budgeted_and_context_checked(tmp_path):
    from test_reader_pdf import make_pdf
    from test_reader_pipeline import SyntheticAbstract
    from research_assistant.reader_pipeline import run_reader
    path = tmp_path / "synthetic.pdf"
    make_pdf(path, texts=("Synthetic method A", "Synthetic method B"))
    class Extractor:
        def analyze(self, chunk):
            return {"claims": [claim("method", chunk["text"], chunk["text"])]}
    resolver = Mock()
    resolver.analyze.return_value = {"fields": [decision("select", [1])]}
    args = dict(abstract_analyzer_factory=SyntheticAbstract, fulltext_analyzer_factory=Extractor,
                reconciler_factory=lambda: resolver, fulltext_options={"reconcile": True})
    result = run_reader([{**paper(), "abstract": "Synthetic abstract"}], {"Synthetic": path}, **args)
    assert result["budget"]["admitted_calls"] == 4
    assert result["paper_analysis"][0]["method"] == "Synthetic method B"
    def counter(text):
        return 100_000 if '"decisions"' in text or '"FieldDecision"' in text else 1
    result = run_reader([{**paper(), "abstract": "Synthetic abstract"}], {"Synthetic": path},
        budget_options={"token_counter": counter}, **args)
    assert result["budget"]["events"][-1]["code"] == "context_budget_exceeded"
    assert resolver.analyze.call_count == 1


def test_invalid_flag_precedes_model_calls():
    factory = Mock()
    with pytest.raises(ValueError, match="boolean"):
        analyze_fulltext_materials([], [], reconcile=1, analyzer_factory=factory)
    factory.assert_not_called()


def test_all_candidates_abstained_status_is_fallback_and_exact_quote_offsets():
    extractor = Mock()
    extractor.analyze.side_effect = [
        {"claims": [claim("method", "A", "method A")]},
        {"claims": [claim("method", "B", "method B")]},
    ]
    resolver = Mock()
    resolver.analyze.return_value = {"fields": [decision("abstain", [])]}
    source = material(("Synthetic method A", "Synthetic method B"))
    result = analyze_fulltext_materials([paper()], [source], analyzer_factory=lambda: extractor,
        reconcile=True, reconciler_factory=lambda: resolver)
    detail = result["details"][0]
    assert detail["status"] == "fallback"
    assert result["paper_analysis"][0]["method"] == ""
    for item in detail["evidence"]:
        text = source["pages"][item["page"] - 1]["text"]
        assert text[item["quote_start"]:item["quote_end"]] == item["quote"]


def test_default_resolver_respects_disabled_models(tmp_path):
    from test_reader_pdf import make_pdf
    from research_assistant.reader_pipeline import run_reader
    path = tmp_path / "synthetic.pdf"
    make_pdf(path, texts=("Synthetic method A", "Synthetic method B"))
    class Extractor:
        def analyze(self, chunk):
            return {"claims": [claim("method", chunk["text"], chunk["text"])]}
    result = run_reader([paper()], {"Synthetic": path}, fulltext_analyzer_factory=Extractor,
                        fulltext_options={"reconcile": True})
    assert result["budget"]["admitted_calls"] == 2
    assert result["details"][0]["status"] == "fallback"
    assert result["details"][0]["issues"][-1]["code"] == "reconciliation_failed"
