from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from research_assistant.search.models import ProviderError
from research_assistant.search.providers import ArxivProvider, SemanticScholarProvider
from research_assistant.search.transport import HttpResponse


class FakeTransport:
    def __init__(self, body):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.requests = []

    def get(self, url, headers=None):
        self.requests.append((url, headers))
        return HttpResponse(self.body, url, "2026-10-15T00:00:00+00:00", hashlib.sha256(self.body).hexdigest())


def feed(entries="", total=0):
    return f'''<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
      <opensearch:totalResults>{total}</opensearch:totalResults>{entries}</feed>'''


def entry(source_id="2401.12345v2", title="Real title", authors="Alice", published="2024-01-22T00:00:00Z"):
    return f'''<entry><id>http://arxiv.org/abs/{source_id}</id><title>{title}</title>
      <author><name>{authors}</name></author><published>{published}</published>
      <summary>A real abstract with\n  whitespace.</summary><arxiv:doi>10.1234/Example</arxiv:doi></entry>'''


def paper(**overrides):
    result = {"paperId": "a" * 40, "title": "Verified title", "authors": [{"name": "Alice"}, {"name": "王明"}], "year": 2024, "abstract": "Actual abstract.", "url": "https://www.semanticscholar.org/paper/verified/" + "a" * 40, "externalIds": {"DOI": "10.1234/Example", "ArXiv": "2401.12345v2"}}
    result.update(overrides)
    return result


def s2_payload(data, total=None):
    return json.dumps({"total": len(data) if total is None else total, "offset": 0, "data": data}, ensure_ascii=False)


def test_arxiv_parses_actual_metadata_and_retains_request_evidence():
    transport = FakeTransport(feed(entry(title="A title\n with spacing"), 1))
    result = ArxivProvider(transport).search("multi-agent research 中文", limit=7)
    hit = result.hits[0]
    assert hit.paper.model_dump() == {"title": "A title with spacing", "authors": ["Alice"], "year": 2024, "abstract": "A real abstract with whitespace.", "url": "https://arxiv.org/abs/2401.12345v2", "source": "arxiv", "relevance_score": None}
    assert hit.source_id == "2401.12345v2"
    assert hit.arxiv_id == "2401.12345"
    assert hit.doi == "10.1234/example"
    assert hit.query == "multi-agent research 中文"
    assert hit.evidence["response_sha256"] == hashlib.sha256(transport.body).hexdigest()
    assert hit.evidence["retrieved_at"] == hit.retrieved_at
    request_url = transport.requests[0][0]
    assert urlsplit(request_url).scheme == "https"
    params = parse_qs(urlsplit(request_url).query)
    assert params["max_results"] == ["7"]
    assert params["search_query"] == ['all:"multi-agent" AND all:"research" AND all:"中文"']


def test_arxiv_old_identifier_is_supported():
    result = ArxivProvider(FakeTransport(feed(entry("math.GT/0309136v1"), 1))).search("topology", limit=2)
    assert result.hits[0].arxiv_id == "math.GT/0309136"


@pytest.mark.parametrize("broken", [entry(title=""), entry(authors=""), entry(source_id="not-an-id"), entry(published="unknown")])
def test_arxiv_skips_single_bad_record_with_visible_warning(broken):
    result = ArxivProvider(FakeTransport(feed(broken + entry(), 2))).search("agents", limit=10)
    assert len(result.hits) == 1
    assert len(result.warnings) == 1


def test_arxiv_truly_empty_feed_is_success():
    assert ArxivProvider(FakeTransport(feed())).search("no match", limit=5).hits == []


@pytest.mark.parametrize("body", ["not xml", "<html/>", '<feed xmlns="http://www.w3.org/2005/Atom"/>', feed(total=2), feed(entry(title=""), 1), feed('<entry><id>http://arxiv.org/api/errors#incorrect_id_format</id></entry>', 1)])
def test_arxiv_malformed_error_and_all_bad_responses_are_not_empty_results(body):
    with pytest.raises(ProviderError):
        ArxivProvider(FakeTransport(body)).search("agents", limit=5)


def test_semantic_scholar_parses_fields_and_key_stays_in_header(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "PRIVATE_API_KEY")
    transport = FakeTransport(s2_payload([paper()]))
    hit = SemanticScholarProvider(transport).search("multi agent", limit=8).hits[0]
    assert hit.paper.authors == ["Alice", "王明"]
    assert hit.paper.year == 2024
    assert hit.paper.abstract == "Actual abstract."
    assert hit.paper.url == paper()["url"]
    assert hit.paper.source == "semantic_scholar"
    assert hit.doi == "10.1234/example"
    assert hit.arxiv_id == "2401.12345"
    url, headers = transport.requests[0]
    assert headers == {"x-api-key": "PRIVATE_API_KEY"}
    assert "PRIVATE_API_KEY" not in url
    assert "PRIVATE_API_KEY" not in json.dumps(hit.evidence)
    assert parse_qs(urlsplit(url).query)["limit"] == ["8"]


def test_semantic_scholar_none_metadata_is_preserved_without_fabrication():
    source = paper(year=None, abstract=None, authors=[], externalIds={}, url=None)
    result = SemanticScholarProvider(FakeTransport(s2_payload([source]))).search("agents", limit=2)
    hit = result.hits[0]
    assert hit.paper.year is None
    assert hit.paper.abstract == ""
    assert hit.paper.authors == []
    assert hit.paper.url == "https://www.semanticscholar.org/paper/" + source["paperId"]
    assert hit.doi == hit.arxiv_id == ""
    assert result.warnings


def test_semantic_scholar_refuses_external_paper_url_and_malformed_optional_data():
    source = paper(url="https://attacker.example/paper/a", year=True, abstract={"bad": 1}, externalIds={"DOI": "made up", "ArXiv": "not real"})
    result = SemanticScholarProvider(FakeTransport(s2_payload([source]))).search("agents", limit=2)
    hit = result.hits[0]
    assert hit.paper.url.startswith("https://www.semanticscholar.org/paper/")
    assert hit.paper.year is None
    assert hit.paper.abstract == ""
    assert hit.arxiv_id == hit.doi == ""
    assert len(result.warnings) >= 4


def test_semantic_scholar_url_must_refer_to_the_actual_paper_id():
    source = paper(url="https://www.semanticscholar.org/paper/" + "b" * 40)
    result = SemanticScholarProvider(FakeTransport(s2_payload([source]))).search("agents", limit=2)
    assert result.hits[0].paper.url.endswith("a" * 40)
    assert result.warnings


def test_semantic_scholar_rejects_noncanonical_identifier():
    with pytest.raises(ProviderError):
        SemanticScholarProvider(FakeTransport(s2_payload([paper(paperId="invented-id")]))).search("agents",limit=2)


def test_empty_result_retains_public_response_evidence():
    response = SemanticScholarProvider(FakeTransport(s2_payload([]))).search("no match",limit=2)
    assert response.response_evidence["request_url"].startswith("https://api.semanticscholar.org/")
    assert len(response.response_evidence["response_sha256"]) == 64


@pytest.mark.parametrize("broken", [None, {}, paper(title=None), paper(paperId=""), paper(authors=None)])
def test_semantic_scholar_skips_single_bad_record_with_warning(broken):
    result = SemanticScholarProvider(FakeTransport(s2_payload([broken, paper()]))).search("agents", limit=5)
    assert len(result.hits) == 1
    assert result.warnings


@pytest.mark.parametrize("body", ["bad json", "null", "[]", '{}', '{"error": "rate limited"}', '{"data": []}', '{"total": true,"data": []}', s2_payload([], 1), s2_payload([{}])])
def test_semantic_scholar_invalid_response_is_an_explicit_failure(body):
    with pytest.raises(ProviderError):
        SemanticScholarProvider(FakeTransport(body)).search("agents", limit=5)


def test_semantic_scholar_empty_data_and_total_zero_is_success():
    assert SemanticScholarProvider(FakeTransport(s2_payload([]))).search("no match", limit=5).hits == []


@pytest.mark.parametrize("provider", [ArxivProvider, SemanticScholarProvider])
@pytest.mark.parametrize("query,limit", [("", 2), ("  ", 2), ("ok", 0), ("ok", 101), ("ok", True)])
def test_invalid_query_or_limit_does_not_perform_io(provider, query, limit):
    transport = FakeTransport(b"unused")
    with pytest.raises(ValueError):
        provider(transport).search(query, limit=limit)
    assert not transport.requests


def test_transport_failure_propagates_and_does_not_become_zero_hits():
    class FailedTransport:
        def get(self, *args, **kwargs):
            raise ProviderError("offline failure")

    for provider in (ArxivProvider, SemanticScholarProvider):
        with pytest.raises(ProviderError, match="offline failure"):
            provider(FailedTransport()).search("agents", limit=5)
