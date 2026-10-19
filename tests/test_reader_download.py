"""Synthetic HTTP/PDF fixtures only. Never contact arXiv or a model."""
import hashlib
import io
import json
from email.message import Message
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from research_assistant import reader_download as downloads
from research_assistant.reader_pipeline import run_reader_with_downloads


@pytest.fixture(autouse=True)
def transport_guard(monkeypatch):
    monkeypatch.setattr(downloads, "_NEXT_REQUEST", 0)
    monkeypatch.setattr(downloads, "_BLOCKED_UNTIL", 0)
    monkeypatch.setattr(downloads, "_open", Mock(side_effect=AssertionError("unmocked network")))


class Response(io.BytesIO):
    def __init__(self, data, headers=None, status=200):
        super().__init__(data)
        self.headers = headers or {}
        self.status = status


def paper(title="Synthetic", url="https://arxiv.org/abs/2401.12345v2"):
    return {"title": title, "authors": [], "source": "arxiv", "url": url,
            "abstract": "Synthetic evidence only"}


@pytest.mark.parametrize("url,expected", [
    ("http://arxiv.org/abs/2401.12345v2", "2401.12345v2"),
    ("https://export.arxiv.org/pdf/hep-th/9901001v1.pdf", "hep-th/9901001v1"),
    ("https://www.arxiv.org/pdf/2401.1234", "2401.1234"),
    ("https://arxiv.org.evil.test/abs/2401.12345", None),
    ("https://user:secret@arxiv.org/abs/2401.12345", None),
    ("https://arxiv.org:443/pdf/2401.12345", None),
    ("https://arxiv.org/pdf/2401.12345?token=secret", None),
    ("https://arxiv.org/pdf/2401.12345#fragment", None),
    ("https://doi.org/10.1234/anything", None),
    ("https://arxiv.org/pdf/../secret", None),
    ("https://arxiv.org/pdf/2401.12345\n", None),
    ("file:///local.pdf", None), ("", None), (None, None)])
def test_source_urls(url, expected):
    result = downloads.arxiv_pdf_url(url)
    assert result == ("https://arxiv.org/pdf/" + expected if expected else None)


def test_streamed_success_and_no_overwrite(tmp_path, monkeypatch):
    data = b"%PDF-synthetic-not-a-real-paper"
    opened = Mock(side_effect=lambda *a: Response(data, {"Content-Length": str(len(data))}))
    monkeypatch.setattr(downloads, "_open", opened)
    destination = tmp_path / "material.pdf"
    receipt = downloads.download_pdf(paper()["url"], destination)
    assert receipt["sha256"] == hashlib.sha256(data).hexdigest()
    assert receipt["bytes"] == len(data) and destination.read_bytes() == data
    assert opened.call_args.args[0].full_url == "https://arxiv.org/pdf/2401.12345v2"
    monkeypatch.setattr(downloads, "_NEXT_REQUEST", 0)
    assert downloads.download_pdf(paper()["url"], destination)["code"] == "download_io_failed"
    assert destination.read_bytes() == data


@pytest.mark.parametrize("data,headers,code", [
    (b"%PDF-longer", {"Content-Length": "999"}, "download_size_limit"),
    (b"%PDF-longer", {}, "download_size_limit"),
    (b"HTML", {}, "invalid_pdf_header"),
    (b"%PDF-", {"Content-Length": "8"}, "incomplete_download"),
    (b"%PDF-", {"Content-Length": "bad"}, "invalid_length"),
    (b"%PDF-", {"Content-Encoding": "gzip"}, "unsupported_encoding")])
def test_invalid_response_cleanup(tmp_path, monkeypatch, data, headers, code):
    response = Response(data, headers)
    monkeypatch.setattr(downloads, "_open", lambda *a: response)
    target = tmp_path / "material.pdf"
    assert downloads.download_pdf(paper()["url"], target, max_bytes=8)["code"] == code
    assert not target.exists() and response.closed


def test_midstream_failure_cleanup(tmp_path, monkeypatch):
    class Broken(Response):
        def read(self, size):
            if self.tell():
                raise TimeoutError("synthetic timeout")
            return super().read(5)
    monkeypatch.setattr(downloads, "_open", lambda *a: Broken(b"%PDF-synthetic"))
    target = tmp_path / "material.pdf"
    assert downloads.download_pdf(paper()["url"], target)["code"] == "download_failed"
    assert not target.exists()


def test_rate_limit_cooldown_and_redirect_refusal(tmp_path, monkeypatch):
    headers = Message()
    headers["Retry-After"] = "600"
    opened = Mock(side_effect=HTTPError(paper()["url"], 429, "synthetic", headers, io.BytesIO()))
    monkeypatch.setattr(downloads, "_open", opened)
    first = downloads.download_pdf(paper()["url"], tmp_path / "a.pdf")
    assert first["code"] == "rate_limited" and first["retry_after_seconds"] == 600
    assert downloads.download_pdf(paper()["url"], tmp_path / "b.pdf")["code"] == "source_cooldown"
    assert opened.call_count == 1
    monkeypatch.setattr(downloads, "_BLOCKED_UNTIL", 0)
    monkeypatch.setattr(downloads, "_NEXT_REQUEST", 0)
    opened.side_effect = HTTPError(paper()["url"], 302, "synthetic", Message(), io.BytesIO())
    assert downloads.download_pdf(paper()["url"], tmp_path / "c.pdf")["code"] == "redirect_refused"
    assert downloads._NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test") is None


def test_request_spacing_without_sleeping(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(downloads.time, "monotonic", lambda: clock[0])
    waits = []
    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(downloads.time, "sleep", sleep)
    monkeypatch.setattr(downloads, "_open", lambda *a: Response(b"%PDF-synthetic"))
    downloads.download_pdf(paper()["url"], tmp_path / "a.pdf")
    downloads.download_pdf(paper()["url"], tmp_path / "b.pdf")
    assert waits == [0, 3]


def test_soft_stream_deadline(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(downloads.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(downloads.time, "sleep", lambda n: None)
    class Slow(Response):
        def read(self, size):
            clock[0] += 21
            return super().read(5)
    monkeypatch.setattr(downloads, "_open", lambda *a: Slow(b"%PDF-synthetic"))
    target = tmp_path / "slow.pdf"
    assert downloads.download_pdf(paper()["url"], target)["code"] == "download_timeout"
    assert not target.exists()


def test_batch_local_priority_request_and_byte_reservations(tmp_path, monkeypatch):
    fetch = Mock(return_value={"status": "failed", "code": "synthetic"})
    monkeypatch.setattr(downloads, "download_pdf", fetch)
    paths, records = downloads.acquire_pdfs([paper("Local"), paper("A"), paper("B"),
        paper("Unsupported", "https://openalex.org/W123")], {" Local ": "local.pdf"}, tmp_path,
        max_bytes=10, max_total_bytes=10)
    assert paths == {" Local ": "local.pdf"} and fetch.call_count == 1
    assert [r.get("code") for r in records] == [None, "synthetic", "download_budget_exceeded", "unsupported_fulltext_url"]
    _, records = downloads.acquire_pdfs([paper("A"), paper("B")], {}, tmp_path, max_requests=1)
    assert records[-1]["code"] == "download_budget_exceeded"


@pytest.mark.parametrize("kwargs", [
    {"download_options": {"interval_seconds": 0}}, {"download_options": {"max_requests": 21}},
    {"download_options": {"timeout_seconds": float("nan")}}, {"download_options": []},
    {"pdf_paths": {"": "bad.pdf"}}, {"pdf_options": {"max_workers": 9}},
    {"fulltext_options": {"max_chunks": 0}}, {"budget_options": {"max_calls": 0}}])
def test_preflight_before_network(kwargs):
    with pytest.raises(ValueError):
        run_reader_with_downloads([paper()], **kwargs)


def test_complete_synthetic_download_parse_extract_and_cleanup(tmp_path, monkeypatch):
    from test_reader_pdf import make_pdf
    from test_reader_pipeline import SyntheticAbstract, SyntheticFulltext
    source = tmp_path / "synthetic.pdf"
    make_pdf(source, texts=("Synthetic method A",))
    monkeypatch.setattr(downloads, "_open", lambda *a: Response(source.read_bytes()))
    paths_seen = []
    original = downloads.download_pdf
    def capture(url, path, **kwargs):
        paths_seen.append(Path(path))
        return original(url, path, **kwargs)
    monkeypatch.setattr(downloads, "download_pdf", capture)
    result = run_reader_with_downloads([paper(), paper("Missing", "https://openalex.org/W123")],
        abstract_analyzer_factory=SyntheticAbstract, fulltext_analyzer_factory=SyntheticFulltext)
    assert result["paper_analysis"][0]["method"] == "Synthetic method A"
    assert result["paper_analysis"][1]["method"] == "Synthetic abstract method"
    assert result["acquisition"][0]["status"] == "ok"
    assert all(not p.exists() and not p.parent.exists() for p in paths_seen)
    assert json.loads(json.dumps(result)) == result


def test_downloads_cleaned_on_analyzer_bug(tmp_path, monkeypatch):
    from test_reader_pdf import make_pdf
    source = tmp_path / "synthetic.pdf"
    make_pdf(source)
    paths = []
    def fetch(url, destination, **kwargs):
        paths.append(destination)
        destination.write_bytes(source.read_bytes())
        return {"status": "ok"}
    monkeypatch.setattr(downloads, "download_pdf", fetch)
    analyzer = Mock()
    analyzer.analyze.side_effect = AttributeError("synthetic bug")
    with pytest.raises(AttributeError):
        run_reader_with_downloads([paper()], abstract_analyzer_factory=lambda: analyzer)
    assert paths and not paths[0].exists() and not paths[0].parent.exists()


def test_transport_failure_continues_with_abstracts(monkeypatch):
    from test_reader_pipeline import SyntheticAbstract
    monkeypatch.setattr(downloads, "_open", Mock(side_effect=URLError("synthetic TLS failure")))
    result = run_reader_with_downloads([paper()], abstract_analyzer_factory=SyntheticAbstract)
    assert result["acquisition"][0]["code"] == "download_failed"
    assert result["paper_analysis"][0]["method"] == "Synthetic abstract method"
