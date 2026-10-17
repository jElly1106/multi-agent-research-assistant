"""Offline integration checks. All paper metadata below is MOCK_ONLY test data.

The fake opener replaces network I/O inside the real HttpTransport, preserving
its official-host validation, pacing, response archiving and provider parsing.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import urlsplit

from research_assistant.agents.search import SearchAgent
from research_assistant.schemas import Paper
from research_assistant.search.config import SearchConfig
from research_assistant.search.crossref import CrossrefProvider
from research_assistant.search.openalex import OpenAlexProvider
from research_assistant.search.ranking import validate_paper_references
from research_assistant.search.transport import HttpTransport


MOCK_ONLY_WORK_ID = "https://openalex.org/W123456789"
MOCK_ONLY_DOI = "10.1234/mock_only_shared"
PAPER_FIELDS = {"title", "authors", "year", "abstract", "url", "source", "relevance_score"}


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Response(BytesIO):
    status = 200


def openalex_body():
    return json.dumps({
        "meta": {"count": 1},
        "results": [{
            "id": MOCK_ONLY_WORK_ID,
            "title": "MOCK_ONLY multimodal forecasting OpenAlex record",
            "publication_year": 2024,
            "doi": "https://doi.org/" + MOCK_ONLY_DOI,
            "authorships": [{"author": {"display_name": "MOCK_ONLY Author"}}],
            "abstract_inverted_index": {"MOCK_ONLY": [0], "multimodal": [1], "forecasting": [2]},
            "primary_location": None,
            "ids": {"openalex": MOCK_ONLY_WORK_ID, "doi": "https://doi.org/" + MOCK_ONLY_DOI},
            "type": "conference-paper",
            "primary_topic": {"field": {"display_name": "Computer Science", "id": "https://openalex.org/fields/17"}},
        }],
    }).encode("utf-8")


def test_real_transport_allows_openalex_paces_one_second_and_archives_exact_bytes(tmp_path):
    body = openalex_body()
    clock, requests = Clock(), []

    def opener(request, *, timeout):
        assert urlsplit(request.full_url).hostname == "api.openalex.org"
        assert timeout == 2.0
        requests.append((request.full_url, clock()))
        return Response(body)

    transport = HttpTransport(
        opener=opener, sleep=clock.sleep, clock=clock, timeout=2,
        max_retries=0, evidence_dir=tmp_path,
    )
    provider = OpenAlexProvider(transport)
    results = [provider.search(f"MOCK_ONLY forecasting {number}", limit=1) for number in range(3)]

    assert [started for _, started in requests] == [0.0, 1.0, 2.0]
    assert clock.sleeps == [1.0, 1.0]
    digest = hashlib.sha256(body).hexdigest()
    assert (tmp_path / f"{digest}.response").read_bytes() == body
    assert len(list(tmp_path.glob("*.response"))) == 1
    receipts = [json.loads(path.read_text("utf-8")) for path in tmp_path.glob("*.json")]
    assert len(receipts) == 3
    assert {receipt["request_url"] for receipt in receipts} == {url for url, _ in requests}
    assert all(receipt["response_sha256"] == digest for receipt in receipts)
    for result in results:
        assert result.response_evidence["route"] == "injected"
        assert result.response_evidence["attempts"] == 1
        assert result.hits[0].evidence["response_sha256"] == digest
        assert Path(result.hits[0].evidence["response_file"]).read_bytes() == body


def test_default_search_source_constructs_openalex_and_returns_valid_seven_field_paper(tmp_path):
    # Only bounds are overridden: the source is the application's real default.
    agent = SearchAgent(config=SearchConfig(max_queries=1, results_per_query=1), audit_dir=tmp_path)
    assert SearchConfig().sources == ("openalex",)
    assert len(agent.providers) == 1
    assert isinstance(agent.providers[0], OpenAlexProvider)
    body, requests, clock = openalex_body(), [], Clock()

    def opener(request, *, timeout):
        requests.append(request.full_url)
        assert urlsplit(request.full_url).hostname == "api.openalex.org"
        return Response(body)

    # Keep the constructed provider; replace only its actual network I/O.
    agent.providers[0].transport = HttpTransport(
        opener=opener, sleep=clock.sleep, clock=clock,
        evidence_dir=tmp_path / "raw", max_retries=0,
    )
    result = agent({"topic": "MOCK_ONLY multimodal forecasting"})

    assert len(requests) == 1
    assert len(result["papers"]) == 1
    paper = result["papers"][0]
    assert set(paper) == PAPER_FIELDS
    assert Paper.model_validate(paper).source == "openalex"
    assert paper["url"] == MOCK_ONLY_WORK_ID
    assert paper["abstract"] == "MOCK_ONLY multimodal forecasting"
    assert 0 <= paper["relevance_score"] <= 1
    validate_paper_references([paper["title"], paper["url"]], result["papers"])
    assert agent.last_audit["status"] == "success"
    assert agent.last_audit["requests"][0]["source"] == "openalex"
    assert list(tmp_path.glob("*.json"))  # The real node saved its audit.


def test_shared_actual_doi_deduplicates_openalex_and_crossref_retaining_both_provenances(tmp_path):
    # Different titles/authors prevent title heuristics from masking DOI matching.
    crossref_body = json.dumps({
        "status": "ok", "message-type": "work-list",
        "message": {"total-results": 1, "items": [{
            "type": "proceedings-article", "DOI": MOCK_ONLY_DOI.upper(),
            "title": ["MOCK_ONLY alternative deposited title"],
            "author": [{"name": "MOCK_ONLY Different Author"}],
            "published": {"date-parts": [[2024]]},
            "abstract": "MOCK_ONLY multimodal forecasting",
        }]},
    }).encode("utf-8")
    bodies = {"api.openalex.org": openalex_body(), "api.crossref.org": crossref_body}
    clock, requests = Clock(), []

    def opener(request, *, timeout):
        host = urlsplit(request.full_url).hostname
        requests.append(host)
        return Response(bodies[host])

    transport = HttpTransport(
        opener=opener, sleep=clock.sleep, clock=clock,
        evidence_dir=tmp_path / "raw", max_retries=0,
    )
    agent = SearchAgent(
        config=SearchConfig(sources=("openalex", "crossref"), max_queries=1, results_per_query=1),
        providers=[OpenAlexProvider(transport), CrossrefProvider(transport)],
        audit_dir=tmp_path,
    )
    result = agent({"topic": "MOCK_ONLY multimodal forecasting"})

    assert requests == ["api.openalex.org", "api.crossref.org"]
    assert len(result["papers"]) == 1
    paper = result["papers"][0]
    assert paper["source"] == "openalex"
    assert paper["url"] == MOCK_ONLY_WORK_ID
    assert set(paper) == PAPER_FIELDS
    assert agent.last_audit["counts"]["duplicates_removed"] == 1
    candidate = agent.last_audit["candidates"][0]
    assert candidate["identifiers"]["dois"] == [MOCK_ONLY_DOI]
    provenance = {entry["source"]: entry for entry in candidate["provenance"]}
    assert set(provenance) == {"openalex", "crossref"}
    assert provenance["openalex"]["url"] == MOCK_ONLY_WORK_ID
    assert provenance["crossref"]["url"] == "https://doi.org/" + MOCK_ONLY_DOI
    for source, host in (("openalex", "api.openalex.org"), ("crossref", "api.crossref.org")):
        evidence = provenance[source]
        assert urlsplit(evidence["request_url"]).hostname == host
        assert evidence["response_sha256"] == hashlib.sha256(bodies[host]).hexdigest()
        assert Path(evidence["response_file"]).read_bytes() == bodies[host]
