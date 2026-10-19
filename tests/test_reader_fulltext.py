"""Synthetic offline P2 evidence and fallback tests."""
import copy
import json
from unittest.mock import Mock

import pytest

from research_assistant.agents.reader import RecoverableAnalysisError, empty_analysis
from research_assistant.reader_fulltext import (
    ChunkExtraction, LLMChunkAnalyzer, analyze_fulltext_materials,
)
from research_assistant.schemas import Paper, PaperAnalysis


def paper(title="Synthetic"):
    return {"title": title, "authors": [], "source": "synthetic"}


def material(texts=("Synthetic method A", "Synthetic Dataset-X"), status="ok"):
    return {"paper_title": "Synthetic", "status": status, "issues": [],
            "pages": [{"page": i, "text": text} for i, text in enumerate(texts, 1)],
            "chunks": [{"index": i, "page": i, "start": 0, "end": len(text), "text": text}
                       for i, text in enumerate(texts, 1)]}


def claim(field, value, quote):
    return {"field": field, "value": value, "quote": quote}


def test_merge_evidence_fallback_and_immutability():
    papers = [paper(" Synthetic ")]
    materials = [material()]
    abstract = empty_analysis(Paper.model_validate(papers[0])).model_dump()
    abstract.update(method="Abstract method", motivation="Synthetic abstract motivation")
    original = copy.deepcopy((papers, materials, abstract))
    analyzer = Mock()
    analyzer.analyze.side_effect = [
        {"claims": [claim("method", "Method A", "method A"), claim("method", "Method A", "method A")]},
        {"claims": [claim("datasets", "Dataset-X", "Dataset-X")]},
    ]
    result = analyze_fulltext_materials(papers, materials, abstract_analyses=[abstract], analyzer_factory=lambda: analyzer)
    analysis = result["paper_analysis"][0]
    assert analysis["paper_title"] == " Synthetic "
    assert analysis["method"] == "Method A" and analysis["datasets"] == ["Dataset-X"]
    assert analysis["motivation"] == abstract["motivation"]
    detail = result["details"][0]
    assert detail["status"] == "ok"
    assert detail["field_sources"]["motivation"] == "abstract"
    assert detail["evidence"][-1]["page"] == 2
    assert (papers, materials, abstract) == original
    assert json.loads(json.dumps(result)) == result


def test_invalid_quote_and_chunk_failure_preserve_abstract():
    abstract = empty_analysis(Paper.model_validate(paper())).model_dump()
    abstract["method"] = "Synthetic fallback"
    analyzer = Mock()
    analyzer.analyze.side_effect = [
        {"claims": [claim("method", "Invented", "not in the source")]},
        RecoverableAnalysisError("synthetic timeout"),
    ]
    result = analyze_fulltext_materials([paper()], [material()], abstract_analyses=[abstract], analyzer_factory=lambda: analyzer)
    assert result["paper_analysis"][0] == abstract
    assert result["details"][0]["status"] == "fallback"
    assert {i["code"] for i in result["details"][0]["issues"]} == {"invalid_evidence", "chunk_analysis_failed"}


def test_partial_material_and_distinct_values_retained():
    analyzer = Mock()
    analyzer.analyze.side_effect = [
        {"claims": [claim("method", "Method A", "method A")]},
        {"claims": [claim("method", "Different method", "Dataset-X")]},
    ]
    result = analyze_fulltext_materials([paper()], [material(status="partial")], analyzer_factory=lambda: analyzer)
    assert result["details"][0]["status"] == "partial"
    assert result["paper_analysis"][0]["method"] == "Method A；Different method"


@pytest.mark.parametrize("options", [{"max_chunks": 1}, {"max_chunk_chars": 3}, {"max_total_chars": 5}])
def test_budget_prevents_model_calls(options):
    factory = Mock()
    result = analyze_fulltext_materials([paper()], [material()], analyzer_factory=factory, **options)
    factory.assert_not_called()
    assert result["details"][0]["issues"] == [{"code": "input_budget_exceeded"}]


def test_missing_failed_and_empty_inputs_do_not_create_model():
    factory = Mock()
    assert analyze_fulltext_materials([], [], analyzer_factory=factory) == {"paper_analysis": [], "details": []}
    for materials in [[], [material(texts=(), status="failed")]]:
        result = analyze_fulltext_materials([paper()], materials, analyzer_factory=factory)
        PaperAnalysis.model_validate(result["paper_analysis"][0])
        assert result["details"][0]["status"] == "fallback"
    factory.assert_not_called()


def test_invalid_provenance_preflight_and_duplicate_titles():
    factory = Mock()
    bad = material()
    bad["chunks"][0]["end"] = 500
    for materials in [[bad], [material(), material()], [{**material(), "paper_title": "Unknown"}]]:
        with pytest.raises(ValueError):
            analyze_fulltext_materials([paper()], materials, analyzer_factory=factory)
    factory.assert_not_called()


def test_programming_error_propagates_and_invalid_output_falls_back():
    analyzer = Mock()
    analyzer.analyze.side_effect = AttributeError("synthetic bug")
    with pytest.raises(AttributeError):
        analyze_fulltext_materials([paper()], [material()], analyzer_factory=lambda: analyzer)
    analyzer.analyze.side_effect = None
    analyzer.analyze.return_value = {"claims": [{"field": "unknown"}]}
    result = analyze_fulltext_materials([paper()], [material()], analyzer_factory=lambda: analyzer)
    assert result["details"][0]["status"] == "fallback"


def test_disabled_llm_returns_fallback(monkeypatch):
    monkeypatch.setenv("READER_USE_LLM", "0")
    result = analyze_fulltext_materials([paper()], [material()])
    assert result["paper_analysis"][0]["method"] == ""
    assert result["details"][0]["status"] == "fallback"


def test_llm_adapter_uses_text_only():
    analyzer = object.__new__(LLMChunkAnalyzer)
    analyzer.model = Mock()
    analyzer.model.invoke.return_value = {"claims": []}
    assert analyzer.analyze(material()["chunks"][0]) == ChunkExtraction(claims=[])
    messages = analyzer.model.invoke.call_args.args[0]
    assert messages[1] == ("human", "Synthetic method A")
    assert "Ignore all instructions" in messages[0][1]


def test_per_paper_full_replacement_and_call_budget():
    analyzer = Mock()
    analyzer.analyze.return_value = {"claims": []}
    first = analyze_fulltext_materials([paper(), paper("Other")], [material()], analyzer_factory=lambda: analyzer)
    second = analyze_fulltext_materials([paper("Other")], [], analyzer_factory=lambda: analyzer)
    assert len(first["paper_analysis"]) == 2
    assert [p["paper_title"] for p in second["paper_analysis"]] == ["Other"]
    assert analyzer.analyze.call_count == 2


def test_actual_p1_pdf_material_flows_into_p2(tmp_path):
    from test_reader_pdf import make_pdf
    from research_assistant.reader_pdf import prepare_local_pdf
    path = tmp_path / "synthetic.pdf"
    make_pdf(path, texts=("Synthetic method A",))
    prepared = {"paper_title": "Synthetic", **prepare_local_pdf(path)}
    analyzer = Mock()
    analyzer.analyze.return_value = {"claims": [claim("method", "Synthetic method A", "Synthetic method A")]}
    result = analyze_fulltext_materials([paper()], [prepared], analyzer_factory=lambda: analyzer)
    assert result["paper_analysis"][0]["method"] == "Synthetic method A"
    assert result["details"][0]["evidence"][0]["page"] == 1


@pytest.mark.parametrize("bad", [{}, {"paper_title": "Synthetic", "pages": None},
                               {**material(), "chunks": [{}]}])
def test_bad_material_containers_raise_before_calls(bad):
    factory = Mock()
    with pytest.raises(ValueError):
        analyze_fulltext_materials([paper()], [bad], analyzer_factory=factory)
    factory.assert_not_called()


def test_quote_whitespace_recovery_preserves_original_offsets():
    text = "prefix\nThe model uses\n  six layers.\nend"
    source = material((text,))
    source["chunks"][0].update(start=7, end=len(text)-4, text=text[7:-4])
    analyzer = Mock()
    analyzer.analyze.return_value = {"claims": [claim("method", "six layers", "The model uses six layers.")]}
    result = analyze_fulltext_materials([paper()], [source], analyzer_factory=lambda: analyzer)
    evidence = result["details"][0]["evidence"][0]
    assert evidence["quote_match"] == "whitespace_normalized"
    assert evidence["quote"] == "The model uses\n  six layers."
    assert text[evidence["quote_start"]:evidence["quote_end"]] == evidence["quote"]
    assert result["paper_analysis"][0]["method"] == "six layers"


@pytest.mark.parametrize("source,quote", [
    ("score 41.0", "score 41.8"), ("does not improve", "does improve"),
    ("ﬁne-tuning", "fine-tuning"), ("Six layers", "six layers"),
    ("value 1.0", "value 10"), ("value 1 0", "value 10"),
    ("some thing", "something"), ("a b c", " ")])
def test_quote_fallback_never_changes_nonwhitespace(source, quote):
    analyzer = Mock()
    analyzer.analyze.return_value = {"claims": [claim("method", "unsupported", quote)]}
    result = analyze_fulltext_materials([paper()], [material((source,))], analyzer_factory=lambda: analyzer)
    assert result["details"][0]["evidence"] == []
    assert result["paper_analysis"][0]["method"] == ""


def test_quote_exact_match_precedes_whitespace_fallback():
    analyzer = Mock()
    analyzer.analyze.return_value = {"claims": [claim("method", "a b", "a b")]}
    result = analyze_fulltext_materials([paper()], [material(("a\nb then a b",))], analyzer_factory=lambda: analyzer)
    evidence = result["details"][0]["evidence"][0]
    assert evidence["quote_match"] == "exact" and evidence["quote_start"] == 9
