"""Synthetic provider outcomes through the actual P0/P2 adapters; no network."""
from unittest.mock import Mock

import pytest
from langchain_openai.chat_models.base import OpenAIRefusalError
from openai import ContentFilterFinishReasonError, LengthFinishReasonError
from openai.types.chat import ChatCompletion

from research_assistant.agents.reader import LLMAbstractAnalyzer, build_reader_node, empty_analysis
from research_assistant.reader_fulltext import LLMChunkAnalyzer, analyze_fulltext_materials
from research_assistant.schemas import Paper


@pytest.fixture(params=["refusal", "filter", "length"])
def provider_error(request):
    if request.param == "refusal":
        return OpenAIRefusalError("Synthetic refusal")
    if request.param == "filter":
        return ContentFilterFinishReasonError()
    completion = ChatCompletion(id="synthetic", choices=[], created=0,
                                model="synthetic", object="chat.completion")
    return LengthFinishReasonError(completion=completion)


def test_p0_provider_outcome_falls_back_and_continues(provider_error):
    first = Paper(title="Synthetic First", authors=[], source="synthetic", abstract="Synthetic evidence")
    second = first.model_copy(update={"title": "Synthetic Second"})
    success = empty_analysis(second).model_copy(update={"method": "Synthetic method"})
    analyzer = object.__new__(LLMAbstractAnalyzer)
    analyzer._structured_llm = Mock()
    analyzer._structured_llm.invoke.side_effect = [provider_error, success]
    result = build_reader_node(lambda: analyzer)({"papers": [first.model_dump(), second.model_dump()]})
    assert result["paper_analysis"][0] == empty_analysis(first).model_dump()
    assert result["paper_analysis"][1]["method"] == "Synthetic method"
    assert analyzer._structured_llm.invoke.call_count == 2


def test_p2_provider_outcome_preserves_abstract_and_continues(provider_error):
    papers = [Paper(title=title, authors=[], source="synthetic") for title in ["Synthetic First", "Synthetic Second"]]
    abstract = empty_analysis(papers[0]).model_copy(update={"method": "Synthetic abstract fallback"})
    text = "Synthetic method evidence"
    materials = [{"paper_title": p.title, "status": "ok", "issues": [],
                  "pages": [{"page": 1, "text": text}],
                  "chunks": [{"index": 1, "page": 1, "start": 0, "end": len(text), "text": text}]}
                 for p in papers]
    analyzer = object.__new__(LLMChunkAnalyzer)
    analyzer.model = Mock()
    analyzer.model.invoke.side_effect = [provider_error, {"claims": [
        {"field": "method", "value": "Synthetic method", "quote": "Synthetic method"}]}]
    result = analyze_fulltext_materials([p.model_dump() for p in papers], materials,
        abstract_analyses=[abstract.model_dump()], analyzer_factory=lambda: analyzer)
    assert result["paper_analysis"][0] == abstract.model_dump()
    assert result["details"][0]["status"] == "fallback"
    assert result["paper_analysis"][1]["method"] == "Synthetic method"
    assert analyzer.model.invoke.call_count == 2
