"""Offline-only OpenAlex adapter tests. No real API is called here."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from research_assistant.search.models import ProviderError
from research_assistant.search.openalex import OpenAlexProvider
from research_assistant.search.transport import HttpResponse


class FakeTransport:
    def __init__(self, body):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.requests = []

    def get(self, url, headers=None):
        self.requests.append((url, headers))
        return HttpResponse(self.body, url, "2026-10-17T03:00:00+00:00", hashlib.sha256(self.body).hexdigest(), "recorded.response", "injected", 1)


def work(**overrides):
    item = {
        "id": "https://openalex.org/W123456", "title": "MOCK_ONLY multimodal forecasting title",
        "publication_year": 2024, "doi": "https://doi.org/10.1234/MOCK_ONLY",
        "authorships": [{"author": {"display_name": "Alice"}}, {"author": {"display_name": "王明"}}],
        "abstract_inverted_index": {"Time": [0], "series": [1], "forecasting": [2, 4], "enables": [3]},
        "primary_location": {
            "landing_page_url": "http://arxiv.org/abs/2401.12345v2", "pdf_url": "https://arxiv.org/pdf/2401.12345v2",
            "source": {"display_name": "arXiv"},
        },
        "ids": {"openalex": "https://openalex.org/W123456", "doi": "https://doi.org/10.1234/MOCK_ONLY"},
        "type": "preprint", "primary_topic": {"display_name": "Time Series", "field": {"display_name": "Computer Science", "id": "https://openalex.org/fields/17"}},
    }
    item.update(overrides)
    return item


def payload(items, total=None):
    return json.dumps({"meta": {"count": len(items) if total is None else total}, "results": items}, ensure_ascii=False)


def search(items, *, total=None, limit=10):
    return OpenAlexProvider(FakeTransport(payload(items, total))).search("multimodal time series", limit=limit)


def test_recovers_real_metadata_and_preserves_origin_evidence():
    transport = FakeTransport(payload([work()], total=80))
    result = OpenAlexProvider(transport).search("  多模态 forecasting  ", limit=5)
    hit = result.hits[0]
    assert hit.paper.model_dump() == {
        "title": "MOCK_ONLY multimodal forecasting title", "authors": ["Alice", "王明"],
        "year": 2024, "abstract": "Time series forecasting enables forecasting",
        "url": "https://openalex.org/W123456", "source": "openalex", "relevance_score": None,
    }
    assert hit.source_id == "W123456"
    assert hit.doi == "10.1234/mock_only"
    assert hit.arxiv_id == "2401.12345"
    assert hit.query == "多模态 forecasting"
    assert hit.evidence["response_sha256"] == hashlib.sha256(transport.body).hexdigest()
    assert hit.evidence["response_file"] == "recorded.response"
    assert hit.evidence["landing_page_url"] == "http://arxiv.org/abs/2401.12345v2"
    assert hit.evidence["pdf_url"] == "https://arxiv.org/pdf/2401.12345v2"
    assert hit.evidence["venue"] == "arXiv"
    assert hit.evidence["field"] == "Computer Science"
    assert result.response_evidence["raw_record_count"] == 1
    assert result.response_evidence["total_results"] == 80
    assert len(transport.requests) == 1  # No landing-page/PDF fetches.
    url, headers = transport.requests[0]
    assert urlsplit(url).netloc == "api.openalex.org"
    assert parse_qs(urlsplit(url).query)["search"] == ["多模态 forecasting"]
    assert parse_qs(urlsplit(url).query)["per-page"] == ["5"]
    assert "abstract_inverted_index" in parse_qs(urlsplit(url).query)["select"][0]
    assert headers is None


@pytest.mark.parametrize("kind", ["article", "conference-paper", "review", "preprint", "book-chapter", "book", "report", "dissertation", "proceedings-article"])
def test_accepts_scholarly_publication_types(kind):
    assert len(search([work(type=kind)]).hits) == 1


@pytest.mark.parametrize("kind", ["dataset", "software", "editorial", "correction", "unknown", "", None])
def test_excludes_nonpaper_types_with_visible_warning(kind):
    result = search([work(type=kind), work()])
    assert len(result.hits) == 1
    assert result.warnings


@pytest.mark.parametrize("broken", [None, {}, work(id="https://attacker.example/W123456"), work(id="https://openalex.org/W123456?x=1"), work(id="W123456"), work(id="https://openalex.org/A123456"), work(title=""), work(authorships=None), work(ids={"openalex": "https://openalex.org/W99999"})])
def test_skips_bad_metadata_without_discarding_good_record(broken):
    result = search([broken, work()])
    assert len(result.hits) == 1
    assert result.warnings


@pytest.mark.parametrize("body", [
    "not json", "[]", "{}", '{"error":"unavailable"}',
    '{"meta":{"count":1},"results":[]}', '{"meta":{"count":0},"results":[{}]}',
    '{"meta":{"count":true},"results":[]}', '{"meta":{"count":-1},"results":[]}',
    '{"meta":{"count":null},"results":[]}', '{"meta":[],"results":[]}',
    payload([None]), payload([work(title="")]), payload([work(type="dataset")]),
    payload([work(), work()], total=1),
])
def test_malformed_and_all_bad_results_are_not_reported_as_zero(body):
    with pytest.raises(ProviderError):
        OpenAlexProvider(FakeTransport(body)).search("agents", limit=3)


def test_legitimate_zero_result_keeps_response_evidence():
    result = search([])
    assert result.hits == []
    assert result.response_evidence["raw_record_count"] == 0
    assert result.response_evidence["total_results"] == 0
    assert result.response_evidence["response_sha256"]


@pytest.mark.parametrize("index", [
    None, {}, [], "generated abstract", {"hello": [1]}, {"hello": [0, 2]},
    {"hello": [0], "world": [0]}, {"hello": [0, 0]}, {"hello": [-1]},
    {"hello": [True]}, {"hello": [0.0]}, {"hello": ["0"]},
    {"hello": [100_000]}, {"hello": []}, {"hello": None}, {"": [0]},
])
def test_invalid_missing_or_incomplete_abstract_never_invents_prose(index):
    result = search([work(abstract_inverted_index=index)])
    assert result.hits[0].paper.abstract == ""
    assert result.warnings


def test_unknown_year_and_authors_stay_unknown_without_fabrication():
    result = search([work(publication_year=None, authorships=[])])
    assert result.hits[0].paper.year is None
    assert result.hits[0].paper.authors == []
    assert result.warnings


@pytest.mark.parametrize("year", [True, "2024", 0, 10000])
def test_invalid_year_is_unknown(year):
    result = search([work(publication_year=year)])
    assert result.hits[0].paper.year is None
    assert result.warnings


def test_only_actual_author_names_are_kept():
    result = search([work(authorships=[{"author": {"display_name": "Alice"}}, None, {"author": None}, {"author": {"display_name": ""}}])])
    assert result.hits[0].paper.authors == ["Alice"]
    assert result.warnings


def test_original_byline_takes_priority_and_conflict_preserves_both_names():
    source = work(authorships=[{"raw_author_name": "MOCK_ONLY Original Author", "author": {"display_name": "MOCK_ONLY Profile Author"}}])
    result = search([source])
    hit = result.hits[0]
    assert hit.paper.authors == ["MOCK_ONLY Original Author"]
    assert hit.evidence["author_name_basis"] == [{
        "author_index": 1, "selected_name": "MOCK_ONLY Original Author", "basis": "raw_author_name",
    }]
    assert hit.evidence["author_name_conflicts"] == [{
        "author_index": 1, "raw_author_name": "MOCK_ONLY Original Author", "display_name": "MOCK_ONLY Profile Author",
    }]
    assert any("采用文献原始署名" in warning and "未判定档案名错误" in warning for warning in result.warnings)
    assert hit.paper.source == "openalex"


@pytest.mark.parametrize("raw_name", [None, "", "  ", 123, [], {}])
def test_missing_or_invalid_original_byline_falls_back_to_actual_profile_name(raw_name):
    result = search([work(authorships=[{"raw_author_name": raw_name, "author": {"display_name": "MOCK_ONLY Profile Author"}}])])
    hit = result.hits[0]
    assert hit.paper.authors == ["MOCK_ONLY Profile Author"]
    assert hit.evidence["author_name_basis"] == [{
        "author_index": 1, "selected_name": "MOCK_ONLY Profile Author", "basis": "author.display_name",
    }]
    assert hit.evidence["author_name_conflicts"] == []
    assert not result.warnings


def test_original_byline_is_valid_even_if_author_profile_missing():
    result = search([work(authorships=[{"raw_author_name": "MOCK_ONLY Original Author", "author": None}])])
    assert result.hits[0].paper.authors == ["MOCK_ONLY Original Author"]
    assert result.hits[0].evidence["author_name_basis"][0]["basis"] == "raw_author_name"
    assert not result.warnings


def test_matching_byline_and_profile_name_is_not_a_conflict():
    result = search([work(authorships=[{"raw_author_name": " MOCK_ONLY Author ", "author": {"display_name": "MOCK_ONLY Author"}}])])
    assert result.hits[0].paper.authors == ["MOCK_ONLY Author"]
    assert result.hits[0].evidence["author_name_conflicts"] == []
    assert result.hits[0].evidence["author_name_basis"][0]["basis"] == "raw_author_name"
    assert not result.warnings


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1/private", "http://169.254.169.254/", "http://[::1]/", "http://localhost/", "http://internal.local/", "http://user:password@publisher.example/", "https://publisher.example:9999/paper", "javascript:alert(1)"])
def test_untrusted_external_url_is_ignored_and_never_requested(url):
    transport = FakeTransport(payload([work(primary_location={"landing_page_url": url, "pdf_url": url})]))
    hit = OpenAlexProvider(transport).search("forecasting", limit=2).hits[0]
    assert hit.paper.url == "https://openalex.org/W123456"
    assert hit.evidence["landing_page_url"] == hit.evidence["pdf_url"] == ""
    assert len(transport.requests) == 1


def test_arxiv_doi_is_retained_for_dedup_without_claiming_arxiv_retrieval():
    hit = search([work(doi="https://doi.org/10.48550/arxiv.2401.12345", primary_location=None)]).hits[0]
    assert hit.arxiv_id == "2401.12345"
    assert hit.paper.source == "openalex"
    assert hit.paper.url == "https://openalex.org/W123456"


def test_response_limit_is_respected():
    assert len(search([work(), work()], limit=1).hits) == 1


def test_does_not_read_or_leak_unverified_api_key(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "PRIVATE_KEY")
    transport = FakeTransport(payload([work()]))
    result = OpenAlexProvider(transport).search("forecasting", limit=1)
    assert "PRIVATE_KEY" not in str(transport.requests)
    assert "PRIVATE_KEY" not in repr(result)


def test_default_transport_uses_direct_first_auto_routing():
    assert OpenAlexProvider().transport.proxy_mode == "auto"


def test_transport_failure_is_propagated_without_fake_papers():
    class BrokenTransport:
        def get(self, url):
            raise ProviderError("HTTP 429", details={"status_code": 429})

    with pytest.raises(ProviderError) as error:
        OpenAlexProvider(BrokenTransport()).search("forecasting", limit=1)
    assert error.value.details["status_code"] == 429


@pytest.mark.parametrize("query,limit", [("", 1), ("a" * 2001, 1), ("agents", 0), ("agents", True), ("agents", 101)])
def test_invalid_inputs_are_rejected_before_network(query, limit):
    transport = FakeTransport(payload([]))
    with pytest.raises(ValueError):
        OpenAlexProvider(transport).search(query, limit=limit)
    assert transport.requests == []
