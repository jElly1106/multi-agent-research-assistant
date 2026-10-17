"""Offline checks for respectful rate-limit handling and failure evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
from urllib.error import HTTPError, URLError

import pytest

from examples.search_demo import main
from research_assistant.agents.search import SearchAgent, SearchUnavailableError
from research_assistant.search.config import SearchConfig
from research_assistant.search.models import ProviderError
from research_assistant.search.transport import HttpTransport


ARXIV_URL = "https://export.arxiv.org/api/query?search_query=all%3Aagents"


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_transport(opener, **kwargs):
    clock = Clock()
    return HttpTransport(opener=opener, sleep=clock.sleep, clock=clock, **kwargs), clock


def assert_retry_at(details, expected_wait):
    retry_at = datetime.fromisoformat(details["retry_at"].replace("Z", "+00:00"))
    assert retry_at.utcoffset() == timedelta(0)
    actual_wait = (retry_at - datetime.now(timezone.utc)).total_seconds()
    assert actual_wait == pytest.approx(expected_wait, abs=3)


def test_429_stops_immediately_without_retry_or_route_change():
    calls = []

    def direct(*args, **kwargs):
        calls.append("direct")
        raise HTTPError(ARXIV_URL, 429, "limited", {"Retry-After": "120"}, None)

    def system(*args, **kwargs):
        calls.append("system")
        raise AssertionError("A 429 must never cause a route switch")

    client, clock = make_transport(direct, max_retries=4, max_retry_after=5)
    client._routes = [("direct", direct), ("system", system)]
    with pytest.raises(ProviderError) as caught:
        client.get(ARXIV_URL)

    details = caught.value.details
    assert calls == ["direct"]
    assert clock.sleeps == []
    assert client._preferred_route == 0
    assert details["request_url"] == ARXIV_URL
    assert details["http_status"] == 429
    assert details["rate_limited"] is True
    assert details["route"] == "direct"
    assert len(details["attempts"]) == 1
    assert details["attempts"][0]["route"] == "direct"
    assert details["attempts"][0]["http_status"] == 429
    assert details["attempts"][0]["outcome"]
    assert details["retry_after"] == "120"
    assert details["retry_after_seconds"] == 120
    assert details["recommended_wait_seconds"] == 120
    assert details["wait_source"] == "server"
    assert_retry_at(details, 120)


def test_429_preserves_long_server_wait_instead_of_capping_and_retrying():
    calls = []

    def opener(*args, **kwargs):
        calls.append(1)
        raise HTTPError(ARXIV_URL, 429, "limited", {"Retry-After": "99999"}, None)

    client, clock = make_transport(opener, max_retries=2, max_retry_after=5)
    with pytest.raises(ProviderError) as caught:
        client.get(ARXIV_URL)

    assert calls == [1]
    assert clock.sleeps == []
    assert caught.value.details["retry_after_seconds"] == 99999
    assert caught.value.details["recommended_wait_seconds"] == 99999
    assert_retry_at(caught.value.details, 99999)


def test_http_date_retry_after_is_recorded_as_server_guidance():
    future = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=600)
    header = format_datetime(future, usegmt=True)

    def opener(*args, **kwargs):
        raise HTTPError(ARXIV_URL, 429, "limited", {"Retry-After": header}, None)

    client, clock = make_transport(opener, max_retries=2, max_retry_after=5)
    with pytest.raises(ProviderError) as caught:
        client.get(ARXIV_URL)

    details = caught.value.details
    assert details["retry_after"] == header
    assert details["retry_after_seconds"] == pytest.approx(600, abs=2)
    assert details["recommended_wait_seconds"] == pytest.approx(600, abs=2)
    assert details["wait_source"] == "server"
    assert clock.sleeps == []
    assert_retry_at(details, 600)


def test_network_fallback_then_429_keeps_complete_attempt_route_chain():
    calls = []

    def direct(*args, **kwargs):
        calls.append("direct")
        raise URLError("proxy details containing API_SECRET")

    def system(*args, **kwargs):
        calls.append("system")
        raise HTTPError(ARXIV_URL, 429, "API_SECRET", {"Retry-After": "60"}, None)

    client, _ = make_transport(direct, max_retries=3)
    client._routes = [("direct", direct), ("system", system)]
    with pytest.raises(ProviderError) as caught:
        client.get(ARXIV_URL, headers={"x-api-key": "API_SECRET"})

    details = caught.value.details
    assert calls == ["direct", "system"]
    assert details["route"] == "system"
    attempts = details["attempts"]
    assert [item["route"] for item in attempts] == ["direct", "system"]
    assert attempts[0]["network_error_type"]
    assert attempts[0]["outcome"]
    assert attempts[1]["http_status"] == 429
    assert attempts[1]["outcome"]
    assert attempts[0]["attempt"] < attempts[1]["attempt"]
    assert "API_SECRET" not in json.dumps(details)
    assert "API_SECRET" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("retry_after", [None, "API_SECRET", "NaN", "Infinity"])
def test_missing_or_invalid_retry_after_uses_local_policy_without_leaking_headers(retry_after):
    headers = {"Set-Cookie": "API_SECRET", "X-Diagnostic": "API_SECRET"}
    if retry_after is not None:
        headers["Retry-After"] = retry_after

    def opener(*args, **kwargs):
        raise HTTPError(ARXIV_URL, 429, "API_SECRET", headers, None)

    client, clock = make_transport(opener, max_retries=3)
    with pytest.raises(ProviderError) as caught:
        client.get(ARXIV_URL, headers={"Authorization": "Bearer API_SECRET"})

    details = caught.value.details
    assert details["wait_source"] == "local_policy"
    assert details["recommended_wait_seconds"] == 300
    assert details.get("retry_after") in (None, "")
    assert details.get("retry_after_seconds") is None
    assert "API_SECRET" not in str(caught.value)
    assert "API_SECRET" not in json.dumps(details)
    assert clock.sleeps == []
    assert_retry_at(details, 300)


def test_503_long_retry_after_stops_instead_of_retrying_before_server_wait():
    calls = []

    def opener(*args, **kwargs):
        calls.append(1)
        raise HTTPError(ARXIV_URL, 503, "unavailable", {"Retry-After": "600"}, None)

    client, clock = make_transport(opener, max_retries=2, max_retry_after=5)
    with pytest.raises(ProviderError) as caught:
        client.get(ARXIV_URL)

    assert calls == [1]
    assert clock.sleeps == []
    assert caught.value.details["http_status"] == 503
    assert caught.value.details["retry_after_seconds"] == 600
    assert caught.value.details["recommended_wait_seconds"] == 600


class LimitedProvider:
    name = "arxiv"

    def __init__(self):
        self.calls = 0
        self.details = {
            "request_url": ARXIV_URL,
            "rate_limited": True,
            "http_status": 429,
            "route": "direct",
            "attempts": [{"attempt": 1, "route": "direct", "outcome": "http_error", "http_status": 429}],
            "retry_after": "60",
            "retry_after_seconds": 60.0,
            "recommended_wait_seconds": 60.0,
            "wait_source": "server",
            "retry_at": "2030-01-01T00:01:00+00:00",
        }

    def search(self, query, *, limit):
        self.calls += 1
        raise ProviderError("检索 API 暂时限流（HTTP 429）", details=self.details)


def test_search_audit_preserves_structured_failure_and_skips_remaining_queries(tmp_path):
    provider = LimitedProvider()
    agent = SearchAgent(config=SearchConfig(max_queries=3), providers=[provider], audit_dir=tmp_path)

    with pytest.raises(SearchUnavailableError):
        agent({"topic": "agents", "search_keywords": ["agents tools", "agents planning"]})

    assert provider.calls == 1
    assert agent.last_audit["status"] == "unavailable"
    assert agent.last_audit["papers"] == []
    assert len(agent.last_audit["requests"]) == 1
    request = agent.last_audit["requests"][0]
    assert request["status"] == "failed"
    assert request["failure_evidence"] == provider.details
    saved = json.loads((tmp_path / (agent.last_audit["run_id"] + ".json")).read_text("utf-8"))
    assert saved["requests"][0]["failure_evidence"] == provider.details


def test_cli_failed_run_says_failure_record_saved_and_keeps_evidence(monkeypatch, tmp_path, capsys):
    provider = LimitedProvider()
    agent = SearchAgent(providers=[provider])
    monkeypatch.setattr("examples.search_demo.create_search_node", lambda **kwargs: agent)
    output = tmp_path / "failed.json"

    assert main(["agents", "--output", str(output)]) == 2

    captured = capsys.readouterr()
    assert "失败记录已保存" in captured.out
    assert "HTTP 429" in captured.err
    assert "未生成任何替代论文" in captured.err
    payload = json.loads(output.read_text("utf-8"))
    assert "检索失败" in payload["notice"]
    assert payload["search_audit"]["status"] == "unavailable"
    assert payload["search_audit"]["papers"] == []
    assert payload["search_audit"]["requests"][0]["failure_evidence"] == provider.details
