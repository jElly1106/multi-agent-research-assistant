"""MOCK_ONLY Crossref fixtures: offline parser tests, not real retrieval evidence."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from research_assistant.search.crossref import CrossrefProvider
from research_assistant.search.models import ProviderError
from research_assistant.search.transport import HttpResponse


class FakeTransport:
    def __init__(self, body, *, evidence_path=""):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.evidence_path = evidence_path
        self.requests = []

    def get(self, url, headers=None):
        self.requests.append((url, headers))
        return HttpResponse(self.body, url, "2026-10-15T00:00:00+00:00", hashlib.sha256(self.body).hexdigest(), self.evidence_path)


def item(**overrides):
    value = {
        "type": "journal-article", "DOI": "10.1234/MOCK_ONLY",
        "title": ["MOCK_ONLY example title"],
        "author": [{"given": "MOCK_ONLY", "family": "Author"}, {"name": "MOCK_ONLY Consortium"}],
        "published-print": {"date-parts": [[2024, 9]]},
        "abstract": "<jats:p>MOCK_ONLY abstract with <jats:italic>emphasis</jats:italic> &amp; entities.</jats:p><jats:p>Second paragraph.</jats:p>",
    }
    value.update(overrides)
    return value


def payload(items, total=None):
    return json.dumps({"status": "ok", "message-type": "work-list", "message": {"items": items, "total-results": len(items) if total is None else total}}, ensure_ascii=False)


def test_parses_doi_metadata_jats_and_response_evidence():
    transport = FakeTransport(payload([item()]), evidence_path="MOCK_ONLY.response")
    result = CrossrefProvider(transport).search("multi agent 中文", limit=7)
    hit = result.hits[0]
    assert hit.paper.model_dump() == {
        "title": "MOCK_ONLY example title", "authors": ["MOCK_ONLY Author", "MOCK_ONLY Consortium"],
        "year": 2024, "abstract": "MOCK_ONLY abstract with emphasis & entities. Second paragraph.",
        "url": "https://doi.org/10.1234/mock_only", "source": "crossref", "relevance_score": None,
    }
    assert hit.source_id == hit.doi == "10.1234/mock_only"
    assert hit.arxiv_id == ""
    assert hit.query == "multi agent 中文"
    assert result.response_evidence["source"] == "crossref"
    assert hit.evidence["response_sha256"] == hashlib.sha256(transport.body).hexdigest()
    assert hit.evidence["response_file"] == "MOCK_ONLY.response"
    assert hit.evidence["retrieved_at"] == hit.retrieved_at
    url, headers = transport.requests[0]
    assert urlsplit(url).scheme == "https"
    assert urlsplit(url).hostname == "api.crossref.org"
    assert parse_qs(urlsplit(url).query) == {"query.bibliographic": ["multi agent 中文"], "rows": ["7"], "sort": ["relevance"], "order": ["desc"]}
    assert headers is None


@pytest.mark.parametrize("work_type", ["journal-article", "proceedings-article", "posted-content", "book-chapter"])
def test_accepts_scholarly_types(work_type):
    assert len(CrossrefProvider(FakeTransport(payload([item(type=work_type)]))).search("mock", limit=2).hits) == 1


def test_non_paper_types_are_filtered_without_claiming_corruption():
    result = CrossrefProvider(FakeTransport(payload([item(type="dataset"), item(type="book")]))).search("mock", limit=3)
    assert result.hits == []
    assert len(result.warnings) == 2
    assert result.response_evidence["request_url"].startswith("https://api.crossref.org/")


def test_missing_optional_fields_stay_missing_and_never_use_created_year():
    source = item(**{"author": [], "abstract": None, "published-print": None, "created": {"date-parts": [[2026]]}})
    result = CrossrefProvider(FakeTransport(payload([source]))).search("mock", limit=2)
    paper = result.hits[0].paper
    assert paper.authors == []
    assert paper.year is None
    assert paper.abstract == ""
    assert len(result.warnings) == 3


def test_publication_year_priority_and_invalid_date_fallback():
    first = item(**{"published-online": {"date-parts": [[2023]]}, "issued": {"date-parts": [[2022]]}})
    second = item(**{"published-print": {"date-parts": [[True]]}, "published-online": {"date-parts": [[2023]]}})
    third = item(**{"published-print": {"date-parts": []}, "published": {"date-parts": [[2021]]}})
    result = CrossrefProvider(FakeTransport(payload([first, second, third]))).search("mock", limit=3)
    assert [hit.paper.year for hit in result.hits] == [2024, 2023, 2021]


@pytest.mark.parametrize("abstract", ["<jats:p>broken", '<!DOCTYPE x [<!ENTITY x "expanded">]><p>&x;</p>', {"invalid": "type"}])
def test_bad_abstract_does_not_invent_text_or_drop_valid_metadata(abstract):
    result = CrossrefProvider(FakeTransport(payload([item(abstract=abstract)]))).search("mock", limit=2)
    assert result.hits[0].paper.abstract == ""
    assert result.warnings


def test_plain_abstract_unescapes_entities():
    result = CrossrefProvider(FakeTransport(payload([item(abstract="MOCK_ONLY plain &amp; honest text.")]))).search("mock", limit=2)
    assert result.hits[0].paper.abstract == "MOCK_ONLY plain & honest text."


def test_doi_url_escapes_special_characters_and_ignores_unrelated_url():
    result = CrossrefProvider(FakeTransport(payload([item(DOI="https://doi.org/10.1234/MOCK#PART?x=1", URL="https://attacker.example")]))).search("mock", limit=2)
    hit = result.hits[0]
    assert hit.doi == "10.1234/mock#part?x=1"
    assert hit.paper.url == "https://doi.org/10.1234/mock%23part%3Fx%3D1"


@pytest.mark.parametrize("broken", [None, {}, item(title=[]), item(DOI="made-up"), item(author=None), item(type=None), item(type=[]), item(type={})])
def test_skips_corrupt_item_but_retains_valid_item_with_warning(broken):
    result = CrossrefProvider(FakeTransport(payload([broken, item()]))).search("mock", limit=2)
    assert len(result.hits) == 1
    assert result.warnings


@pytest.mark.parametrize("body", ["not JSON", "null", "[]", "{}", '{"status":"failed"}',
    '{"status":"ok","message-type":"work","message":{}}',
    '{"status":"ok","message-type":"work-list","message":[]}',
    '{"status":"ok","message-type":"work-list","message":{"items":[],"total-results":true}}',
    payload([], 2), payload([item()], 0), payload([item(DOI="invalid")])])
def test_invalid_and_all_corrupt_responses_are_explicit_failure(body):
    with pytest.raises(ProviderError):
        CrossrefProvider(FakeTransport(body)).search("mock", limit=2)


def test_true_empty_response_retains_public_evidence():
    result = CrossrefProvider(FakeTransport(payload([]))).search("mock", limit=2)
    assert result.hits == []
    assert len(result.response_evidence["response_sha256"]) == 64
    assert result.response_evidence["source_id"] == ""


@pytest.mark.parametrize("query,limit", [("", 2), ("  ", 2), ("x" * 2001, 2), (None, 2), ("mock", 0), ("mock", 101), ("mock", True)])
def test_invalid_query_or_limit_never_performs_io(query, limit):
    transport = FakeTransport(b"unused")
    with pytest.raises(ValueError):
        CrossrefProvider(transport).search(query, limit=limit)
    assert not transport.requests


def test_transport_failures_propagate_instead_of_becoming_zero_hits():
    class FailedTransport:
        def get(self, *args, **kwargs):
            raise ProviderError("MOCK_ONLY HTTP 429 failure")

    with pytest.raises(ProviderError, match="HTTP 429"):
        CrossrefProvider(FailedTransport()).search("mock", limit=2)
