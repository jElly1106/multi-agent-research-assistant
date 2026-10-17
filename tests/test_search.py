"""Offline acceptance tests for member 2.

Every paper in this file is explicitly MOCK_ONLY. Official-looking URLs test
normalisation/validation only; they are not evidence of a real retrieved paper.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from research_assistant.agents.search import SearchUnavailableError, create_search_node
from research_assistant.graph import build_research_graph
from research_assistant.schemas import Paper
from research_assistant.search.config import SearchConfig
from research_assistant.search.models import ProviderError, ProviderResult, SearchHit


PAPER_FIELDS = {"title", "authors", "year", "abstract", "url", "source", "relevance_score"}


def hit(
    number: int = 1,
    *,
    title: str | None = None,
    abstract: str = "MOCK_ONLY: time series forecasting with text fusion and multimodal models.",
    year: int | None = 2024,
    doi: str = "",
    arxiv_id: str | None = None,
    source: str = "arxiv",
) -> SearchHit:
    identifier = arxiv_id or f"2401.{number:05d}"
    url = (
        f"https://arxiv.org/abs/{identifier}"
        if source == "arxiv"
        else f"https://www.semanticscholar.org/paper/{number:040x}"
    )
    return SearchHit(
        paper=Paper(
            title=title or f"MOCK_ONLY: Time Series Text Fusion Experiment {number}",
            authors=["MOCK_ONLY Author"],
            year=year,
            abstract=abstract,
            url=url,
            source=source,
        ),
        source_id=identifier if source == "arxiv" else f"{number:040x}",
        doi=doi,
        arxiv_id=identifier if source == "arxiv" else "",
        retrieved_at="2026-10-15T00:00:00Z",
        evidence={
            "request_url": "https://export.arxiv.org/api/query?search_query=MOCK_ONLY",
            "response_sha256": "a" * 64,
            "mock_only": True,
        },
    )


class FakeProvider:
    """Injected transport boundary: no HTTP calls occur in these tests."""

    def __init__(self, hits=(), *, name="arxiv", error=None):
        self.name = name
        self.hits = list(hits)
        self.error = error
        self.calls = []

    def search(self, query, *, limit):
        self.calls.append((query, limit))
        if self.error:
            raise self.error
        return ProviderResult(hits=copy.deepcopy(self.hits))


def make_agent(provider, **kwargs):
    config = SearchConfig(min_relevance=0, max_queries=1, **kwargs)
    return create_search_node(config=config, providers=[provider])


def state(**updates):
    result = {
        "topic": "multimodal time series forecasting",
        "research_questions": ["时间序列如何融合文本信息？"],
        "search_keywords": ["time series text fusion"],
    }
    result.update(updates)
    return result


def test_public_output_schema_json_and_input_immutability():
    provider = FakeProvider([hit()])
    agent = make_agent(provider)
    incoming = state(paper_analysis=[{"MOCK_ONLY": "unmodified"}])
    original = copy.deepcopy(incoming)

    result = agent(incoming)

    assert len(result["papers"]) == 1
    paper = result["papers"][0]
    assert set(paper) == PAPER_FIELDS
    assert Paper.model_validate(paper).authors == ["MOCK_ONLY Author"]
    assert 0 <= paper["relevance_score"] <= 1
    assert incoming == original
    assert set(result) <= {"papers", "errors"}
    json.dumps(result, ensure_ascii=False, allow_nan=False)
    json.dumps(agent.last_audit, ensure_ascii=False, allow_nan=False)
    assert provider.calls


@pytest.mark.parametrize("incoming", [{}, {"topic": ""}, {"topic": "  "}, {"topic": None}])
def test_empty_topic_is_rejected_before_retrieval(incoming):
    provider = FakeProvider([hit()])
    with pytest.raises(ValueError):
        make_agent(provider)(incoming)
    assert not provider.calls


@pytest.mark.parametrize(
    "kwargs",
    [
        {"top_k": 0}, {"top_k": -1}, {"top_k": True}, {"top_k": 101},
        {"max_queries": 0}, {"results_per_query": 0},
        {"year_from": 2025, "year_to": 2024}, {"year_to": 9999},
        {"min_relevance": -0.1}, {"min_relevance": 1.1},
        {"min_relevance": float("nan")}, {"min_relevance": float("inf")},
        {"keyword_match": "neither"}, {"timeout": 0}, {"max_retries": -1},
        {"sources": ()}, {"sources": ("invented",)}, {"required_keywords": ("",)},
    ],
)
def test_invalid_configuration_is_explicit(kwargs):
    with pytest.raises((TypeError, ValueError)):
        SearchConfig(**kwargs)


def test_questions_generate_english_domain_keywords_without_fixed_coordinator_queries():
    provider = FakeProvider([hit()])
    result = create_search_node(
        config=SearchConfig(min_relevance=0, max_queries=3), providers=[provider]
    )(
        {"topic": "多模态时间序列预测", "research_questions": ["时间序列如何融合文本信息？"]}
    )
    query = " ".join(q for q, _ in provider.calls).lower()
    assert "time" in query and "series" in query
    assert "forecast" in query
    assert "text" in query and "fusion" in query
    assert result["papers"]


def test_query_and_result_budgets_are_passed_to_provider():
    provider = FakeProvider([hit()])
    config = SearchConfig(min_relevance=0, max_queries=2, results_per_query=7)
    create_search_node(config=config, providers=[provider])(
        state(search_keywords=["text time series", "cross attention fusion", "language model time series"])
    )
    assert len(provider.calls) == 2
    assert all(limit == 7 for _, limit in provider.calls)


def test_critic_query_has_priority_over_coordinator_keywords():
    provider = FakeProvider([hit()])
    make_agent(provider)(
        state(critic_result={"decision": "FAIL", "new_search_queries": ["contrastive multimodal alignment"]})
    )
    assert "contrastive" in provider.calls[0][0]
    assert "alignment" in provider.calls[0][0]


def test_optional_model_generates_queries_but_never_paper_metadata():
    provider = FakeProvider([hit()])
    model = Mock()
    model.invoke.return_value = {"queries": ["language model temporal text forecasting"]}
    agent = create_search_node(
        config=SearchConfig(max_queries=1, min_relevance=0), providers=[provider], keyword_model=model
    )
    result = agent(state())
    model.invoke.assert_called_once()
    assert "language" in provider.calls[0][0]
    assert result["papers"][0]["title"] == hit().paper.title


@pytest.mark.parametrize(
    "response",
    [None, "invalid", {"queries": []}, {"queries": [""]},
     {"papers": [{"title": "MOCK_ONLY fabricated LLM paper"}]}],
)
def test_bad_keyword_model_output_falls_back_without_inventing_papers(response):
    provider = FakeProvider([hit()])
    model = Mock()
    model.invoke.return_value = response
    agent = create_search_node(
        config=SearchConfig(max_queries=1, min_relevance=0), providers=[provider], keyword_model=model
    )
    result = agent(state())
    assert len(result["papers"]) == 1
    assert "fabricated" not in json.dumps(result["papers"])
    assert "time" in provider.calls[0][0]
    assert result.get("errors") or "模型" in json.dumps(agent.last_audit, ensure_ascii=False)


def test_keyword_model_failure_has_safe_rule_based_fallback():
    model = Mock()
    model.invoke.side_effect = TimeoutError("MOCK_ONLY model timeout")
    provider = FakeProvider([hit()])
    result = create_search_node(
        config=SearchConfig(max_queries=1, min_relevance=0), providers=[provider], keyword_model=model
    )(state())
    assert result["papers"]
    assert provider.calls


def test_duplicate_arxiv_versions_and_title_variants_collapse():
    first = hit(1, arxiv_id="2401.00001v1", title="MOCK_ONLY: Time-Series Text Fusion")
    revised = hit(1, arxiv_id="2401.00001v2", title="MOCK_ONLY: Time-Series Text Fusion")
    title_variant = hit(2, title="MOCK_ONLY time series text fusion", source="semantic_scholar")
    papers = create_search_node(config=SearchConfig(min_relevance=0,max_queries=1),providers=[
        FakeProvider([first, revised]), FakeProvider([title_variant],name="semantic_scholar")])(state())["papers"]
    assert len(papers) == 1


def test_matching_titles_with_different_explicit_arxiv_ids_remain_distinct():
    title = "MOCK_ONLY: Time Series Text Fusion"
    papers = make_agent(FakeProvider([hit(1, title=title),hit(2,title=title)]))(state())["papers"]
    assert len(papers) == 2


def test_cross_database_doi_duplicates_collapse():
    first = hit(1, doi="https://doi.org/10.1234/MOCK_ONLY.TEST")
    duplicate = hit(2, doi="10.1234/mock_only.test", source="semantic_scholar")
    arxiv = FakeProvider([first])
    semantic = FakeProvider([duplicate], name="semantic_scholar")
    agent = create_search_node(
        config=SearchConfig(min_relevance=0, max_queries=1), providers=[arxiv, semantic]
    )
    assert len(agent(state())["papers"]) == 1


def test_matching_titles_with_conflicting_dois_remain_distinct():
    title = "MOCK_ONLY: Time Series Text Fusion"
    papers = make_agent(FakeProvider([
        hit(1, title=title, doi="10.1234/mock_only.a"),
        hit(2, title=title, doi="10.1234/mock_only.b"),
    ]))(state())["papers"]
    assert len(papers) == 2


def test_same_title_in_different_years_remains_distinct():
    title = "MOCK_ONLY: Time Series Text Fusion"
    papers = make_agent(FakeProvider([hit(1, title=title, year=2023), hit(2, title=title, year=2024)]))(
        state()
    )["papers"]
    assert {p["year"] for p in papers} == {2023, 2024}


def test_year_filter_is_inclusive_and_unknown_year_does_not_slip_through():
    provider = FakeProvider([hit(1, year=2022), hit(2, year=2023), hit(3, year=2024), hit(4, year=None)])
    result = make_agent(provider, year_from=2023, year_to=2024)(state())
    assert {p["year"] for p in result["papers"]} == {2023, 2024}


@pytest.mark.parametrize("mode,expected", [("any", {1, 2}), ("all", {1})])
def test_required_and_excluded_keyword_filters(mode, expected):
    provider = FakeProvider([
        hit(1, abstract="MOCK_ONLY text fusion cross attention"),
        hit(2, title="MOCK_ONLY Text Forecasting", abstract="MOCK_ONLY text"),
        hit(3, title="MOCK_ONLY Text Fusion Excluded", abstract="MOCK_ONLY text fusion withdrawn"),
        hit(4, title="MOCK_ONLY Weather", abstract="MOCK_ONLY rainfall temperature"),
    ])
    result = make_agent(
        provider, required_keywords=("text", "fusion"), excluded_keywords=("withdrawn",), keyword_match=mode
    )(state())
    assert {int(p["url"].rsplit(".", 1)[1]) for p in result["papers"]} == expected


def test_explicit_keyword_filter_keeps_common_research_words():
    provider = FakeProvider([hit(1,title="MOCK_ONLY Language Model",abstract="MOCK_ONLY model"),
                             hit(2,title="MOCK_ONLY Time Series Forecasting",abstract="MOCK_ONLY forecast")])
    required = make_agent(provider,required_keywords=("model",))(state())["papers"]
    assert len(required) == 1 and "Language Model" in required[0]["title"]
    excluded = make_agent(provider,excluded_keywords=("model",))(state())["papers"]
    assert len(excluded) == 1 and "Language Model" not in excluded[0]["title"]


def test_relevance_filter_removes_unrelated_papers_before_top_k():
    relevant = hit(1)
    unrelated = hit(2, title="MOCK_ONLY Ancient Ceramic Painting", abstract="MOCK_ONLY archaeology pottery pigments")
    agent = create_search_node(
        config=SearchConfig(top_k=1, max_queries=1, min_relevance=0.1),
        providers=[FakeProvider([unrelated, relevant])],
    )
    papers = agent(state())["papers"]
    assert len(papers) == 1
    assert papers[0]["title"] == relevant.paper.title
    assert papers[0]["relevance_score"] >= 0.1


def test_top_k_limits_unique_new_papers_and_ranking_is_descending():
    result = make_agent(FakeProvider([hit(i) for i in range(1, 7)]), top_k=2)(state())
    assert len(result["papers"]) == 2
    scores = [p["relevance_score"] for p in result["papers"]]
    assert scores == sorted(scores, reverse=True)
    assert len({p["url"] for p in result["papers"]}) == 2


def test_feedback_round_preserves_existing_papers_and_adds_top_k_new():
    existing = hit(1).paper.model_dump()
    provider = FakeProvider([hit(1), hit(2), hit(3)])
    incoming = state(
        papers=[existing],
        critic_result={"decision": "FAIL", "new_search_queries": ["text multimodal fusion"]},
    )
    original = copy.deepcopy(incoming)
    papers = make_agent(provider, top_k=1)(incoming)["papers"]
    assert len(papers) == 2
    assert existing["url"] in {p["url"] for p in papers}
    assert incoming == original


@pytest.mark.parametrize("url,source", [
    ("https://example.com/fake-paper", "arxiv"),
    ("https://arxiv.org.evil.example/abs/2401.00001", "arxiv"),
    ("https://arxiv.org/abs/2401.00001", "stub"),
])
def test_untrusted_existing_papers_cannot_be_laundered_into_search_output(url, source):
    existing = hit().paper.model_dump()
    existing.update(url=url, source=source)
    with pytest.raises(ValueError):
        make_agent(FakeProvider([hit(2)]))(state(papers=[existing]))


def test_successful_zero_hits_is_distinct_from_upstream_outage():
    agent = make_agent(FakeProvider())
    result = agent(state())
    assert result["papers"] == []
    assert result.get("errors")
    assert isinstance(agent.last_audit, dict) and agent.last_audit


def test_one_provider_failure_keeps_other_provider_real_boundary_results():
    bad = FakeProvider(name="semantic_scholar", error=ProviderError("MOCK_ONLY HTTP 429"))
    good = FakeProvider([hit()])
    agent = create_search_node(
        config=SearchConfig(min_relevance=0, max_queries=1), providers=[bad, good]
    )
    result = agent(state())
    assert len(result["papers"]) == 1
    assert result["papers"][0]["source"] == "arxiv"
    assert result.get("errors")
    assert bad.calls and good.calls


def test_all_provider_requests_failing_raises_instead_of_silently_returning_fake_or_empty():
    agent = make_agent(FakeProvider(error=ProviderError("MOCK_ONLY HTTP timeout")))
    with pytest.raises(SearchUnavailableError):
        agent(state())
    assert isinstance(agent.last_audit, dict)


def test_audit_artifact_records_queries_urls_and_is_json(tmp_path):
    provider = FakeProvider([hit()])
    agent = create_search_node(
        config=SearchConfig(min_relevance=0, max_queries=1), providers=[provider], audit_dir=tmp_path
    )
    result = agent(state())
    files = list(Path(tmp_path).rglob("*.json"))
    assert files, "Requested audit_dir should receive a reusable evidence artifact"
    parsed = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    serialized = json.dumps(parsed, ensure_ascii=False)
    assert result["papers"][0]["url"] in serialized
    assert provider.calls[0][0] in serialized
    assert "MOCK_ONLY" in serialized


def test_real_graph_performs_two_search_rounds_and_preserves_papers(monkeypatch):
    monkeypatch.setenv("COORDINATOR_USE_LLM", "0")

    class RoundProvider(FakeProvider):
        def search(self, query, *, limit):
            self.calls.append((query, limit))
            # The second result overlaps the first, verifying cross-round dedupe.
            numbers = [1] if len(self.calls) == 1 else [1, 2]
            return ProviderResult(hits=[hit(number) for number in numbers])

    provider = RoundProvider()
    search = make_agent(provider, top_k=1)
    seen_by_reader = []

    def reader(current):
        seen_by_reader.append([p["url"] for p in current["papers"]])
        return {"paper_analysis": [{"paper_title": p["title"]} for p in current["papers"]]}

    def critic(current):
        if len(current["papers"]) == 1:
            return {"critic_result": {"decision": "FAIL", "new_search_queries": ["contrastive fusion evidence"]}}
        return {"critic_result": {"decision": "PASS"}}

    graph = build_research_graph(
        search_node=search,
        reader_node=reader,
        analyst_node=lambda current: {"method_summary": {"MOCK_ONLY": "analysis boundary"}},
        critic_node=critic,
        writer_node=lambda current: {"final_report": {"MOCK_ONLY": "integration test", "count": len(current["papers"])}},
    )
    result = graph.invoke({"topic": "Multimodal Time Series Forecasting", "critic_round": 0, "max_critic_rounds": 2})
    assert result["critic_round"] == 2
    assert result["critic_result"]["decision"] == "PASS"
    assert len(result["papers"]) == 2
    assert len(seen_by_reader) == 2
    assert set(seen_by_reader[0]) <= set(seen_by_reader[1])
    assert "contrastive" in provider.calls[1][0]
    assert result["final_report"]["count"] == 2
