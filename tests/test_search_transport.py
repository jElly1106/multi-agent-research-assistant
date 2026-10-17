from __future__ import annotations

import hashlib
from http.client import IncompleteRead
from io import BytesIO
import json
from urllib.error import HTTPError, URLError

import pytest

from research_assistant.search.models import ProviderError
from research_assistant.search.transport import HttpTransport


ARXIV_URL = "https://export.arxiv.org/api/query?search_query=all%3Aagents"
S2_URL = "https://api.semanticscholar.org/graph/v1/paper/search?query=agents"


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


class Response(BytesIO):
    status = 200


def transport(opener, **kwargs):
    clock = Clock()
    return HttpTransport(opener=opener, sleep=clock.sleep, clock=clock, **kwargs), clock


def test_success_preserves_evidence_and_archives_exact_bytes_without_header(tmp_path):
    body = b'{"data": [], "total": 0}'
    calls = []

    def opener(request, *, timeout):
        calls.append((request, timeout))
        return Response(body)

    client, _ = transport(opener, timeout=4.5, evidence_dir=tmp_path)
    result = client.get(S2_URL, headers={"x-api-key": "SECRET_HEADER_ONLY"})
    assert result.body == body
    assert result.url == S2_URL
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert result.retrieved_at.endswith("+00:00")
    assert calls[0][1] == 4.5
    assert calls[0][0].get_header("X-api-key") == "SECRET_HEADER_ONLY"
    assert (tmp_path / f"{result.sha256}.response").read_bytes() == body
    receipts = list(tmp_path.glob("*.json"))
    assert len(receipts) == 1
    meta = json.loads(receipts[0].read_text("utf-8"))
    assert meta["response_sha256"] == result.sha256
    assert meta["request_url"] == S2_URL
    assert "SECRET_HEADER_ONLY" not in json.dumps(meta)
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("url", [
    "http://export.arxiv.org/api/query", "https://attacker.example/api/query",
    "https://api.semanticscholar.org.attacker.example/", "https://user:pass@export.arxiv.org/api/query",
    "https://export.arxiv.org:444/api/query", "https://export.arxiv.org/api/query#secret",
])
def test_only_official_https_api_hosts_are_requested(url):
    calls = []
    client, _ = transport(lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ProviderError, match="HTTPS"):
        client.get(url)
    assert calls == []


@pytest.mark.parametrize("url,interval", [(ARXIV_URL, 3.0), (S2_URL, 1.0)])
def test_pacing_applies_between_successive_requests(url, interval):
    starts = []
    clock = Clock()

    def opener(*args, **kwargs):
        starts.append(clock())
        return Response(b"ok")

    client = HttpTransport(opener=opener, sleep=clock.sleep, clock=clock)
    client.get(url)
    client.get(url)
    client.get(url)
    assert starts == [0.0, interval, interval * 2]


def test_rate_limit_stops_without_truncating_retry_after():
    starts = []
    clock = Clock()

    def opener(*args, **kwargs):
        starts.append(clock())
        if len(starts) == 1:
            raise HTTPError(ARXIV_URL, 429, "rate limited", {"Retry-After": "99999"}, None)
        return Response(b"ok")

    client = HttpTransport(opener=opener, sleep=clock.sleep, clock=clock, max_retries=1, max_retry_after=5)
    with pytest.raises(ProviderError) as caught:
        client.get(ARXIV_URL)
    assert starts == [0.0]
    assert caught.value.details["retry_after_seconds"] == 99999
    assert clock.sleeps == []


def test_network_failure_is_bounded_and_does_not_leak_credentials():
    calls = []

    def opener(*args, **kwargs):
        calls.append(1)
        raise URLError("proxy failure containing API_SECRET")

    client, clock = transport(opener, max_retries=2)
    with pytest.raises(ProviderError) as caught:
        client.get(S2_URL, headers={"x-api-key": "API_SECRET"})
    assert len(calls) == 3
    assert "API_SECRET" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert clock.now >= 2.0


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_do_not_retry_or_include_upstream_error_text(status):
    calls = []

    def opener(*args, **kwargs):
        calls.append(1)
        raise HTTPError(S2_URL, status, "API_SECRET", {}, None)

    client, _ = transport(opener)
    with pytest.raises(ProviderError) as caught:
        client.get(S2_URL)
    assert str(status) in str(caught.value)
    assert "API_SECRET" not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize("body,message", [(b"abcdef", "大小限制"), (b"  ", "空响应")])
def test_oversized_or_empty_success_is_explicit_failure(body, message):
    client, _ = transport(lambda *args, **kwargs: Response(body), max_response_bytes=5)
    with pytest.raises(ProviderError, match=message):
        client.get(ARXIV_URL)


def test_retryable_server_failure_can_recover():
    calls = []

    def opener(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise HTTPError(S2_URL, 503, "unavailable", {}, None)
        return Response(b"ok")

    client, _ = transport(opener)
    assert client.get(S2_URL).body == b"ok"
    assert len(calls) == 3


def test_identical_response_bytes_do_not_overwrite_distinct_request_receipts(tmp_path):
    body = b'{"data": [], "total": 0}'
    client, _ = transport(lambda *args, **kwargs: Response(body), evidence_dir=tmp_path)
    client.get(S2_URL + "&query=one")
    client.get(S2_URL + "&query=two")
    receipts = [json.loads(path.read_text("utf-8")) for path in tmp_path.glob("*.json")]
    assert {r["request_url"] for r in receipts} == {S2_URL + "&query=one", S2_URL + "&query=two"}
    assert len(list(tmp_path.glob("*.response"))) == 1


def test_truncated_network_response_is_retried():
    calls = []

    def opener(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise IncompleteRead(b"partial", 100)
        return Response(b"ok")

    client, _ = transport(opener, max_retries=1)
    assert client.get(S2_URL).body == b"ok"
    assert len(calls) == 2


def test_invalid_secret_header_does_not_reach_network_or_error_message():
    calls = []
    client, _ = transport(lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ProviderError) as caught:
        client.get(S2_URL, headers={"x-api-key": "SECRET\x00VALUE"})
    assert "SECRET" not in str(caught.value)
    assert calls == []


def test_redirect_is_refused_without_making_destination_request():
    from research_assistant.search.transport import _NoRedirect
    with pytest.raises(ProviderError, match="重定向"):
        _NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://attacker.example/")


@pytest.mark.parametrize("kwargs", [{"timeout": 0}, {"timeout": float("inf")}, {"max_retries": -1}, {"max_retries": True}, {"max_response_bytes": 0}, {"max_retry_after": -1}])
def test_invalid_transport_limits_are_rejected(kwargs):
    with pytest.raises(ValueError):
        HttpTransport(**kwargs)
