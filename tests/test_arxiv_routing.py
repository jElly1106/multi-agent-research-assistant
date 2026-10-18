"""Offline regression tests for local arXiv route selection and bounded recovery."""
from __future__ import annotations

from io import BytesIO
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler
import ssl

import pytest

from research_assistant.search.models import ProviderError
from research_assistant.search.providers import ArxivProvider
from research_assistant.search import transport as transport_module
from research_assistant.search.transport import HttpTransport, _NoRedirect


ARXIV_URL = "https://export.arxiv.org/api/query?search_query=all%3Aagents"
EMPTY_FEED = (b'<feed xmlns="http://www.w3.org/2005/Atom" '
              b'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
              b'<opensearch:totalResults>0</opensearch:totalResults></feed>')


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Response(BytesIO):
    status = 200


class Routes:
    """Replace every network opener; outcomes represent only transport behavior."""

    def __init__(self, monkeypatch, *, direct=(), system=(), proxies=None):
        self.clock = Clock()
        self.builds = []
        self.calls = []
        self.outcomes = {"direct": list(direct), "system": list(system)}
        monkeypatch.setattr(transport_module, "getproxies", lambda: (
            {"https": "http://127.0.0.1:7890"} if proxies is None else proxies
        ))
        monkeypatch.setattr(transport_module, "build_opener", self.build_opener)

    def build_opener(self, *handlers):
        # urllib supplies its normal certificate-verifying HTTPS handler.
        # No route may replace it with a handler carrying an insecure context.
        assert not any(isinstance(handler, HTTPSHandler) for handler in handlers)
        assert any(isinstance(handler, _NoRedirect) for handler in handlers)
        proxy_handlers = [handler for handler in handlers if isinstance(handler, ProxyHandler)]
        if proxy_handlers:
            assert len(proxy_handlers) == 1 and proxy_handlers[0].proxies == {}
            route = "direct"
        else:
            route = "system"
        self.builds.append(route)

        def open_request(request, *, timeout):
            self.calls.append((route, self.clock(), request.full_url, timeout))
            assert request.full_url.startswith("https://export.arxiv.org/api/query?")
            queue = self.outcomes[route]
            outcome = queue.pop(0) if queue else b"ok"
            if isinstance(outcome, BaseException):
                raise outcome
            return Response(outcome)

        return SimpleNamespace(open=open_request)

    def client(self, **kwargs):
        return HttpTransport(sleep=self.clock.sleep, clock=self.clock, **kwargs)


@pytest.mark.parametrize("mode,expected_builds,expected_route", [
    ("auto", ["direct", "system"], "direct"),
    ("direct", ["direct"], "direct"),
    ("system", ["system"], "system"),
])
def test_explicit_modes_select_only_their_configured_route(monkeypatch, mode, expected_builds, expected_route):
    routes = Routes(monkeypatch)
    client = routes.client(proxy_mode=mode, timeout=4.5)
    result = client.get(ARXIV_URL)
    assert routes.builds == expected_builds
    assert [call[0] for call in routes.calls] == [expected_route]
    assert routes.calls[0][3] == 4.5
    assert result.route == expected_route
    assert result.attempts == 1


def test_other_sources_keep_transport_system_default(monkeypatch):
    routes = Routes(monkeypatch)
    result = routes.client().get(ARXIV_URL)
    assert routes.builds == ["system"]
    assert result.route == "system"


@pytest.mark.parametrize("proxies", [{}, {"ftp": "http://localhost:7890"}])
def test_auto_without_http_proxy_never_builds_a_system_fallback(monkeypatch, proxies):
    routes = Routes(monkeypatch, proxies=proxies, direct=[TimeoutError(), b"ok"])
    result = routes.client(proxy_mode="auto", max_retries=1).get(ARXIV_URL)
    assert routes.builds == ["direct"]
    assert [call[0] for call in routes.calls] == ["direct", "direct"]
    assert result.route == "direct" and result.attempts == 2


def test_auto_fallback_preserves_evidence_pacing_and_reuses_successful_route(monkeypatch, tmp_path):
    routes = Routes(monkeypatch, direct=[TimeoutError()], system=[EMPTY_FEED, EMPTY_FEED])
    client = routes.client(proxy_mode="auto", max_retries=1, evidence_dir=tmp_path)
    result = ArxivProvider(transport=client).search("agents", limit=5)
    assert result.hits == []
    assert result.response_evidence["route"] == "system"
    assert result.response_evidence["attempts"] == 2
    receipt = json.loads(next(tmp_path.glob("*.json")).read_text("utf-8"))
    assert receipt["route"] == "system" and receipt["attempts"] == 2
    assert receipt["request_url"] == result.response_evidence["request_url"]
    assert (tmp_path / receipt["response_file"]).read_bytes() == EMPTY_FEED
    # A second query starts with the previously successful system route.
    second = client.get(ARXIV_URL)
    assert second.route == "system" and second.attempts == 1
    assert [(call[0], call[1]) for call in routes.calls] == [
        ("direct", 0.0), ("system", 3.0), ("system", 6.0),
    ]


@pytest.mark.parametrize("budget,expected", [
    (0, ["direct"]),
    (1, ["direct", "system"]),
    (2, ["direct", "system", "direct"]),
])
def test_network_fallback_shares_original_retry_budget(monkeypatch, budget, expected):
    routes = Routes(monkeypatch,
                    direct=[URLError("PRIVATE_PROXY_DETAILS")] * 3,
                    system=[URLError("PRIVATE_PROXY_DETAILS")] * 3)
    with pytest.raises(ProviderError) as caught:
        routes.client(proxy_mode="auto", max_retries=budget).get(ARXIV_URL)
    assert [call[0] for call in routes.calls] == expected
    assert len(routes.calls) == budget + 1
    assert "PRIVATE_PROXY_DETAILS" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("status", [503])
def test_http_server_errors_retry_same_route(monkeypatch, status):
    error = HTTPError(ARXIV_URL, status, "upstream message", {"Retry-After": "5"}, None)
    routes = Routes(monkeypatch, direct=[error, b"ok"])
    result = routes.client(proxy_mode="auto", max_retries=1).get(ARXIV_URL)
    assert [(call[0], call[1]) for call in routes.calls] == [("direct", 0.0), ("direct", 5.0)]
    assert result.route == "direct" and result.attempts == 2


def test_http_client_error_does_not_retry_or_switch_route(monkeypatch):
    routes = Routes(monkeypatch, direct=[HTTPError(ARXIV_URL, 400, "bad query", {}, None)])
    with pytest.raises(ProviderError, match="HTTP 400"):
        routes.client(proxy_mode="auto", max_retries=2).get(ARXIV_URL)
    assert [call[0] for call in routes.calls] == ["direct"]


def test_certificate_failure_stays_https_and_does_not_disable_tls_verification(monkeypatch):
    tls_error = URLError(ssl.SSLCertVerificationError("certificate verification failed"))
    routes = Routes(monkeypatch, direct=[tls_error], system=[tls_error])
    with pytest.raises(ProviderError):
        routes.client(proxy_mode="auto", max_retries=1).get(ARXIV_URL)
    assert [call[0] for call in routes.calls] == ["direct", "system"]
    # Routes.build_opener also asserts that neither path overrides urllib's
    # default HTTPS handler, and open_request refuses every non-HTTPS URL.
    assert all(call[2].startswith("https://") for call in routes.calls)


@pytest.mark.parametrize("mode", ["", "automatic", None])
def test_unknown_proxy_mode_is_rejected_before_constructing_openers(monkeypatch, mode):
    routes = Routes(monkeypatch)
    with pytest.raises(ValueError, match="proxy_mode"):
        routes.client(proxy_mode=mode)
    assert routes.builds == [] and routes.calls == []


def test_arxiv_defaults_auto_and_explicit_mode_overrides_environment(monkeypatch):
    routes = Routes(monkeypatch)
    monkeypatch.delenv("ARXIV_PROXY_MODE", raising=False)
    assert ArxivProvider().transport.proxy_mode == "auto"
    monkeypatch.setenv("ARXIV_PROXY_MODE", "system")
    assert ArxivProvider().transport.proxy_mode == "system"
    assert ArxivProvider(proxy_mode="direct").transport.proxy_mode == "direct"
    assert routes.calls == []
