"""Synthetic OpenAlex metadata and arXiv URLs; no real API or model requests."""
import json
from unittest.mock import Mock

import pytest

from research_assistant import reader_sources
from research_assistant.reader_download import acquire_pdfs
from research_assistant.reader_download import validate_download_options
from research_assistant.schemas import Paper
from research_assistant.search.models import ProviderError
from research_assistant.search.transport import HttpResponse


@pytest.fixture
def metadata(monkeypatch):
    monkeypatch.setattr(reader_sources, "_BLOCKED_UNTIL", 0)
    fetch = Mock(side_effect=AssertionError("unmocked metadata request"))
    monkeypatch.setattr("research_assistant.search.transport.HttpTransport.get", fetch)
    return fetch


def paper():
    return Paper(title="SYNTHETIC paper", authors=[], source="openalex", url="https://openalex.org/W123")


def response(**changes):
    work = {"id": paper().url, "title": paper().title,
            "locations": [{"landing_page_url": "https://arxiv.org/abs/2401.12345"}]}
    work.update(changes)
    return HttpResponse(json.dumps(work).encode(), "synthetic", "synthetic", "synthetic")


def test_resolves_secondary_location_without_changing_paper(metadata):
    metadata.side_effect = None
    metadata.return_value = response(primary_location={"pdf_url": "https://publisher.example/paper.pdf"})
    p = paper()
    original = p.model_dump()
    assert reader_sources.openalex_arxiv_url(p) == ("https://arxiv.org/pdf/2401.12345", None)
    metadata.assert_called_once_with("https://api.openalex.org/works/W123")
    assert p.model_dump() == original


@pytest.mark.parametrize("changes,code", [
    ({"id": "https://openalex.org/W999"}, "metadata_identity_mismatch"),
    ({"title": "Different synthetic paper"}, "metadata_identity_mismatch"),
    ({"locations": [{"pdf_url": "https://arxiv.org.evil.test/pdf/2401.12345"}]}, "no_supported_fulltext"),
    ({"locations": None}, "no_supported_fulltext"),
    ({"locations": [{"pdf_url": "https://arxiv.org/pdf/2401.12345"},
                    {"pdf_url": "https://arxiv.org/pdf/2401.54321"}]}, "ambiguous_fulltext_url"),
])
def test_rejects_unsupported_or_conflicting_metadata(metadata, changes, code):
    metadata.side_effect = None
    metadata.return_value = response(**changes)
    assert reader_sources.openalex_arxiv_url(paper()) == (None, code)


def test_rate_limit_cooldown_survives_next_lookup(metadata):
    metadata.side_effect = ProviderError("synthetic", details={"rate_limited": True,
                                                             "recommended_wait_seconds": 600})
    assert reader_sources.openalex_arxiv_url(paper())[1] == "metadata_rate_limited"
    assert reader_sources.openalex_arxiv_url(paper())[1] == "metadata_rate_limited"
    assert metadata.call_count == 1


@pytest.mark.parametrize("body", [b"invalid", b"[]", b"null"])
def test_invalid_response_is_a_fallback(metadata, body):
    metadata.side_effect = None
    metadata.return_value = HttpResponse(body, "synthetic", "synthetic", "synthetic")
    assert reader_sources.openalex_arxiv_url(paper())[1] == "invalid_metadata"


def test_metadata_disabled_local_priority_budget_and_failure(tmp_path, metadata):
    p = paper().model_dump()
    assert acquire_pdfs([p], {}, tmp_path)[1][0]["code"] == "unsupported_fulltext_url"
    acquire_pdfs([p], {p["title"]: "local.pdf"}, tmp_path, resolve_openalex=True)
    metadata.assert_not_called()
    metadata.side_effect = ProviderError("synthetic unavailable")
    second = {**p, "title": "SYNTHETIC second", "url": "https://openalex.org/W456"}
    records = acquire_pdfs([p, second], {}, tmp_path, resolve_openalex=True, max_metadata_requests=1)[1]
    assert [r["code"] for r in records] == ["metadata_unavailable", "metadata_budget_exceeded"]
    assert metadata.call_count == 1


@pytest.mark.parametrize("url", ["https://openalex.org/W123?secret=x", "https://openalex.org.evil.test/W123"])
def test_invalid_work_url_never_requested(metadata, url):
    assert reader_sources.openalex_arxiv_url(paper().model_copy(update={"url": url}))[1] == "unsupported_fulltext_url"
    metadata.assert_not_called()


@pytest.mark.parametrize("options", [{"resolve_openalex": 1}, {"max_metadata_requests": 0},
                                    {"max_metadata_requests": True}, {"max_metadata_requests": 21}])
def test_invalid_resolution_options_rejected_before_work(options):
    with pytest.raises(ValueError):
        validate_download_options(**options)
