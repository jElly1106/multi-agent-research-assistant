"""Crossref's public scholarly metadata API; no generated paper records.

Crossref often has no abstract, so its genuine records can aid discovery without
being suitable for a later abstract-only Reader. Missing metadata stays missing.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote, urlencode
import xml.etree.ElementTree as ET

from ..schemas import Paper
from .models import ProviderError, ProviderResult, SearchHit
from .providers import _doi, _evidence, _finish, _text, _validate_query
from .transport import HttpTransport


_SCHOLARLY_TYPES = frozenset({"journal-article", "proceedings-article", "posted-content", "book-chapter"})
_DATE_FIELDS = ("published-print", "published-online", "published", "issued")
_BLOCK_TAGS = frozenset({"p", "title", "sec", "list", "list-item", "statement", "disp-formula"})


def _publication_year(item: dict) -> int | None:
    """Use a publication year, never metadata indexing/deposit dates."""
    for field in _DATE_FIELDS:
        date = item.get(field)
        if not isinstance(date, dict):
            continue
        parts = date.get("date-parts")
        if not isinstance(parts, list) or not parts or not isinstance(parts[0], list) or not parts[0]:
            continue
        year = parts[0][0]
        if isinstance(year, int) and not isinstance(year, bool) and 1000 <= year <= 9999:
            return year
    return None


def _abstract_text(value: str) -> str:
    """Read plain text or a JATS fragment without executing external entities."""
    if "<" not in value:
        return _text(html.unescape(value))
    # Crossref fragments commonly use a jats prefix without declaring it.
    # Reject declarations instead of accepting entities or a document prolog.
    if "<!DOCTYPE" in value.upper() or "<!ENTITY" in value.upper():
        raise ValueError("XML declarations are not abstract content")
    try:
        root = ET.fromstring('<root xmlns:jats="http://www.ncbi.nlm.nih.gov/JATS1">' + value + "</root>")
    except (ET.ParseError, ValueError):
        raise ValueError("malformed abstract markup") from None
    fragments: list[str] = []

    def visit(element: ET.Element) -> None:
        block = element.tag.rsplit("}", 1)[-1] in _BLOCK_TAGS
        if block:
            fragments.append(" ")
        if element.text:
            fragments.append(element.text)
        for child in element:
            visit(child)
            if child.tail:
                fragments.append(child.tail)
        if block:
            fragments.append(" ")

    visit(root)
    return _text(html.unescape("".join(fragments)))


class CrossrefProvider:
    name = "crossref"
    endpoint = "https://api.crossref.org/works"

    def __init__(self, transport=None, *, timeout: float = 20.0, max_retries: int = 2, evidence_dir: str | Path | None = None):
        self.transport = transport if transport is not None else HttpTransport(timeout=timeout, max_retries=max_retries, evidence_dir=evidence_dir)

    def search(self, query: str, *, limit: int) -> ProviderResult:
        query = _validate_query(query, limit)
        request_url = self.endpoint + "?" + urlencode({
            "query.bibliographic": query,
            "rows": limit,
            "sort": "relevance",
            "order": "desc",
        })
        response = self.transport.get(request_url)
        try:
            payload = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise ProviderError("Crossref 返回了无法解析的 JSON 响应。") from None
        if not isinstance(payload, dict) or payload.get("status") != "ok" or payload.get("message-type") != "work-list":
            raise ProviderError("Crossref 返回了 API 错误或无效的检索结果对象。")
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ProviderError("Crossref 响应缺少有效的 message 对象。")
        data, total = message.get("items"), message.get("total-results")
        if not isinstance(data, list) or isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ProviderError("Crossref 响应缺少有效的 items/total-results 字段。")
        if (total == 0 and data) or (total > 0 and not data):
            raise ProviderError("Crossref 的 total-results 与论文条目不一致。")
        hits: list[SearchHit] = []
        warnings: list[str] = []
        eligible_count = 0
        for index, item in enumerate(data[:limit], 1):
            if not isinstance(item, dict):
                eligible_count += 1
                warnings.append(f"Crossref 第 {index} 条记录不是对象，已跳过。")
                continue
            work_type = item.get("type")
            if isinstance(work_type, str) and work_type not in _SCHOLARLY_TYPES:
                warnings.append(f"Crossref 第 {index} 条记录不是支持的学术论文类型，已跳过。")
                continue
            eligible_count += 1
            raw_title = item.get("title")
            title = _text(raw_title[0]) if isinstance(raw_title, list) and raw_title else ""
            doi = _doi(item.get("DOI"))
            if not isinstance(work_type, str) or work_type not in _SCHOLARLY_TYPES or not title or not doi:
                warnings.append(f"Crossref 第 {index} 条记录缺少有效的学术类型、标题或 DOI，已跳过。")
                continue
            raw_authors = item.get("author", [])
            if not isinstance(raw_authors, list):
                warnings.append(f"Crossref {doi} 缺少有效的作者列表，已跳过。")
                continue
            authors = []
            for author in raw_authors:
                if isinstance(author, dict):
                    name = " ".join(filter(None, (_text(author.get("given")), _text(author.get("family")))))
                    # Some publishers deposit a collective author in name only.
                    name = name or _text(author.get("name"))
                    if name:
                        authors.append(name)
            if not authors or len(authors) != len(raw_authors):
                warnings.append(f"Crossref {doi} 的作者信息缺失或不完整。")
            year = _publication_year(item)
            if year is None:
                warnings.append(f"Crossref {doi} 未提供有效的发表年份，保留为未知。")
            raw_abstract = item.get("abstract")
            abstract = ""
            if isinstance(raw_abstract, str) and raw_abstract.strip():
                try:
                    abstract = _abstract_text(raw_abstract)
                except ValueError:
                    warnings.append(f"Crossref {doi} 的摘要标记无法解析，保留为空。")
            if not abstract:
                warnings.append(f"Crossref {doi} 未提供可用摘要。")
            hits.append(SearchHit(
                paper=Paper(title=title, authors=authors, year=year, abstract=abstract, url="https://doi.org/" + quote(doi, safe="/():;._-"), source=self.name),
                source_id=doi, doi=doi, query=query, retrieved_at=response.retrieved_at,
                evidence=_evidence(response, self.name, doi),
            ))
        # Unsupported work types are deliberate filtering, not corrupt records.
        # A valid feed containing only books/datasets is a genuine zero-paper hit.
        result = _finish(hits, warnings, eligible_count, self.name, response)
        result.response_evidence["raw_record_count"] = len(data[:limit])
        return result
