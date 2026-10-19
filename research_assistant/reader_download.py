"""Opt-in, small-batch arXiv PDF acquisition; no paper discovery."""
from __future__ import annotations

import hashlib
import http.client
import math
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_LOCK = threading.Lock()
_NEXT_REQUEST = 0.0
_BLOCKED_UNTIL = 0.0
_ID = r"(?:\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})(?:v[1-9]\d*)?"


def arxiv_pdf_url(url):
    """Only recognized official record/PDF URLs; never resolve DOI or HTML."""
    if not isinstance(url, str) or any(c.isspace() for c in url):
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}
                or parsed.username or parsed.password or parsed.port is not None
                or parsed.query or parsed.fragment):
            return None
    except ValueError:
        return None
    match = re.fullmatch(r"/(?:abs|pdf)/(" + _ID + r")(?:\.pdf)?", parsed.path)
    return "https://arxiv.org/pdf/" + match[1] if match else None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(request, timeout):
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


def validate_download_options(*, max_requests=5, max_bytes=20 * 1024 * 1024,
                              max_total_bytes=50 * 1024 * 1024, timeout_seconds=20,
                              interval_seconds=3):
    for name, value in [("max_requests", max_requests), ("max_bytes", max_bytes),
                        ("max_total_bytes", max_total_bytes)]:
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if max_requests > 20:
        raise ValueError("small-batch acquisition allows at most 20 requests")
    for name, value, minimum in [("timeout_seconds", timeout_seconds, 0),
                                  ("interval_seconds", interval_seconds, 3)]:
        if (type(value) not in (int, float) or not math.isfinite(value)
                or value <= 0 or value < minimum or value > 60):
            raise ValueError(f"invalid {name}")


def _retry_delay(value):
    try:
        if value and value.strip().isdigit():
            return max(300, int(value))
        if value:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(300, (date - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        pass
    return 300


def download_pdf(url, destination, *, max_bytes=20 * 1024 * 1024,
                 timeout_seconds=20, interval_seconds=3):
    """Download to a new temporary path owned by the caller; structured failures.

    Request timeout is a socket-operation timeout, not a hard batch deadline.
    Redirects and retries are disabled. Process-wide lock serializes this module.
    """
    global _NEXT_REQUEST, _BLOCKED_UNTIL
    validate_download_options(max_bytes=max_bytes, timeout_seconds=timeout_seconds,
                              interval_seconds=interval_seconds)
    canonical = arxiv_pdf_url(url)
    if canonical is None:
        return {"status": "failed", "code": "unsupported_fulltext_url"}
    receipt = {"url": canonical, "status": "failed", "bytes": 0}
    path = Path(destination)
    created = False
    with _LOCK:
        if time.monotonic() < _BLOCKED_UNTIL:
            return {**receipt, "code": "source_cooldown"}
        time.sleep(max(0, _NEXT_REQUEST - time.monotonic()))
        _NEXT_REQUEST = time.monotonic() + interval_seconds
        try:
            request = Request(canonical, headers={"User-Agent": "ReaderAgent/0.1 (personal research)",
                                                  "Accept": "application/pdf", "Accept-Encoding": "identity"})
            with _open(request, timeout_seconds) as response:
                if response.status != 200:
                    return {**receipt, "code": "http_error", "http_status": response.status}
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    return {**receipt, "code": "unsupported_encoding"}
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isdigit() or int(length) > max_bytes):
                    return {**receipt, "code": "download_size_limit" if length.isdigit() else "invalid_length"}
                digest = hashlib.sha256()
                count = 0
                prefix = b""
                deadline = time.monotonic() + timeout_seconds
                with path.open("xb") as stream:
                    created = True
                    while True:
                        if time.monotonic() >= deadline:
                            return {**receipt, "code": "download_timeout"}
                        block = response.read(min(65536, max_bytes - count + 1))
                        if not block:
                            break
                        count += len(block)
                        if count > max_bytes:
                            return {**receipt, "code": "download_size_limit"}
                        prefix = (prefix + block)[:5]
                        stream.write(block)
                        digest.update(block)
                if prefix != b"%PDF-":
                    return {**receipt, "code": "invalid_pdf_header"}
                if length is not None and count != int(length):
                    return {**receipt, "code": "incomplete_download"}
                receipt.update(status="ok", bytes=count, sha256=digest.hexdigest())
                return receipt
        except HTTPError as exc:
            try:
                if exc.code == 429:
                    delay = _retry_delay((exc.headers or {}).get("Retry-After"))
                    _BLOCKED_UNTIL = time.monotonic() + delay
                    return {**receipt, "code": "rate_limited", "http_status": 429,
                            "retry_after_seconds": delay}
                return {**receipt, "code": "redirect_refused" if 300 <= exc.code < 400 else "http_error",
                        "http_status": exc.code}
            finally:
                exc.close()
        except (URLError, TimeoutError, http.client.HTTPException):
            return {**receipt, "code": "download_failed"}
        except OSError:
            return {**receipt, "code": "download_io_failed"}
        finally:
            if created and receipt["status"] != "ok":
                path.unlink(missing_ok=True)


def acquire_pdfs(papers, pdf_paths, directory, **options):
    """Caller owns directory lifetime; only missing local mappings are acquired."""
    from .agents.reader import _prepare_papers
    from .reader_materials import prepare_paper_materials
    validate_download_options(**options)
    prepared = _prepare_papers(papers)
    prepare_paper_materials([], pdf_paths)  # Mapping validation, no parsing.
    paths = dict(pdf_paths)
    local = {title.strip() for title in paths}
    records, requests, total = [], 0, 0
    for index, paper in enumerate(prepared):
        title = paper.title.strip()
        if title in local:
            records.append({"paper_title": paper.title, "status": "local"})
            continue
        url = arxiv_pdf_url(paper.url)
        if url is None:
            records.append({"paper_title": paper.title, "status": "failed", "code": "unsupported_fulltext_url"})
            continue
        remaining = options.get("max_total_bytes", 50 * 1024 * 1024) - total
        if requests >= options.get("max_requests", 5) or remaining <= 0:
            records.append({"paper_title": paper.title, "status": "failed", "code": "download_budget_exceeded"})
            continue
        destination = Path(directory) / f"paper-{index}.pdf"
        receipt = download_pdf(url, destination,
            max_bytes=min(options.get("max_bytes", 20 * 1024 * 1024), remaining),
            timeout_seconds=options.get("timeout_seconds", 20), interval_seconds=options.get("interval_seconds", 3))
        requests += 1
        # Charge all attempted per-file allowances, including failed transfers,
        # so repeated incomplete streams cannot bypass the batch byte budget.
        total += min(options.get("max_bytes", 20 * 1024 * 1024), remaining)
        records.append({"paper_title": paper.title, **receipt})
        if receipt["status"] == "ok":
            paths[paper.title] = destination
    return paths, records
