"""Resolve a supplied OpenAlex work to an official arXiv copy, never search."""
from __future__ import annotations

import json
import re
import time

from .reader_download import arxiv_pdf_url

_BLOCKED_UNTIL = 0.0


def openalex_arxiv_url(paper, *, timeout_seconds=20):
    """Bounded official metadata lookup; refuse identity mismatches and other hosts."""
    from .search.models import ProviderError
    from .search.transport import HttpTransport

    global _BLOCKED_UNTIL

    match = re.fullmatch(r"https://openalex\.org/(W[1-9]\d*)", paper.url)
    if paper.source != "openalex" or match is None:
        return None, "unsupported_fulltext_url"
    if time.monotonic() < _BLOCKED_UNTIL:
        return None, "metadata_rate_limited"
    transport = HttpTransport(timeout=timeout_seconds, max_retries=0,
                              max_response_bytes=2 * 1024 * 1024)
    try:
        response = transport.get("https://api.openalex.org/works/" + match[1])
        work = json.loads(response.body)
    except ProviderError as exc:
        if exc.details.get("rate_limited"):
            delay = exc.details.get("recommended_wait_seconds") or 300
            _BLOCKED_UNTIL = time.monotonic() + max(300, delay)
        return None, ("metadata_rate_limited" if exc.details.get("rate_limited")
                      else "metadata_unavailable")
    except (ValueError, UnicodeDecodeError):
        return None, "invalid_metadata"
    if not isinstance(work, dict):
        return None, "invalid_metadata"
    title = work.get("title")
    if (work.get("id") != paper.url or not isinstance(title, str)
            or " ".join(title.split()).casefold() != " ".join(paper.title.split()).casefold()):
        return None, "metadata_identity_mismatch"
    locations = [work.get("primary_location"), work.get("best_oa_location")]
    if isinstance(work.get("locations"), list):
        locations.extend(work["locations"])
    urls = set()
    for location in locations:
        if not isinstance(location, dict):
            continue
        for field in ("pdf_url", "landing_page_url"):
            url = arxiv_pdf_url(location.get(field))
            if url:
                urls.add(url)
    if len(urls) > 1:
        return None, "ambiguous_fulltext_url"
    return (next(iter(urls)), None) if urls else (None, "no_supported_fulltext")
