"""Official arXiv and Semantic Scholar adapters, without an LLM dependency."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
import xml.etree.ElementTree as ET

from ..schemas import Paper
from .models import ProviderError, ProviderResult, SearchHit
from .transport import HttpResponse, HttpTransport


_ATOM = "{http://www.w3.org/2005/Atom}"
_OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_ARXIV_ID = re.compile(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Za-z]{2})?/\d{7})(?:v\d+)?\Z")


def _text(value) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _xml_text(parent: ET.Element, name: str) -> str:
    child = parent.find(name)
    return _text("".join(child.itertext())) if child is not None else ""


def _validate_query(query: str, limit: int) -> str:
    query = _text(query)
    if not query or len(query) > 2000:
        raise ValueError("query 必须为 1 到 2000 字符的非空字符串")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit 必须为 1 到 100 的整数")
    return query


def _doi(value) -> str:
    value = _text(value)
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    return value.lower() if re.fullmatch(r"10\.\d{4,9}/\S+", value) else ""


def _arxiv_id(value) -> str:
    value = _text(value)
    if not _ARXIV_ID.fullmatch(value):
        return ""
    return re.sub(r"v\d+$", "", value)


def _arxiv_expression(query: str) -> str:
    # Natural-language words are data, never caller-supplied arXiv query DSL.
    # Explicit AND avoids the API's broad implicit-OR space semantics.
    words = re.findall(r"[^\W_]+(?:[-.][^\W_]+)*", query, flags=re.UNICODE)
    if not words:
        raise ValueError("arXiv query 必须包含有效关键词")
    return " AND ".join(f'all:"{word}"' for word in dict.fromkeys(words))


def _evidence(response: HttpResponse, source: str, source_id: str) -> dict:
    result = {
        "source": source,
        "source_id": source_id,
        "request_url": response.url,
        "response_sha256": response.sha256,
        "retrieved_at": response.retrieved_at,
        "route": response.route,
        "attempts": response.attempts,
    }
    if response.evidence_path:
        result["response_file"] = response.evidence_path
    return result


def _finish(hits: list[SearchHit], warnings: list[str], count: int, source: str, response: HttpResponse) -> ProviderResult:
    if count and not hits:
        detail = "；".join(warnings[:3])
        raise ProviderError(f"{source} 返回了 {count} 条记录，但没有可用论文：{detail}")
    evidence = _evidence(response, source, "")
    evidence["raw_record_count"] = count
    return ProviderResult(hits=hits, warnings=warnings, response_evidence=evidence)


class ArxivProvider:
    name = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    def __init__(self, transport=None, *, timeout: float = 20.0, max_retries: int = 2, evidence_dir: str | Path | None = None, proxy_mode: str | None = None):
        self.transport = transport if transport is not None else HttpTransport(timeout=timeout, max_retries=max_retries, evidence_dir=evidence_dir, proxy_mode=proxy_mode or os.getenv("ARXIV_PROXY_MODE", "auto"))

    def search(self, query: str, *, limit: int) -> ProviderResult:
        query = _validate_query(query, limit)
        request_url = self.endpoint + "?" + urlencode({
            "search_query": _arxiv_expression(query),
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        })
        response = self.transport.get(request_url)
        try:
            feed = ET.fromstring(response.body)
        except (ET.ParseError, ValueError):
            raise ProviderError("arXiv 返回了无法解析的 XML 响应。") from None
        if feed.tag != _ATOM + "feed":
            raise ProviderError("arXiv 响应不是有效的 Atom feed。")
        entries = feed.findall(_ATOM + "entry")
        for entry in entries:
            if "/api/errors" in _xml_text(entry, _ATOM + "id"):
                raise ProviderError("arXiv API 返回错误条目；请检查检索词语法或稍后重试。")
        total_text = _xml_text(feed, _OPENSEARCH + "totalResults")
        if not re.fullmatch(r"\d+", total_text):
            raise ProviderError("arXiv feed 缺少有效的 totalResults，无法确认检索结果。")
        total = int(total_text)
        if (total == 0 and entries) or (total > 0 and not entries):
            raise ProviderError("arXiv feed 的 totalResults 与论文条目不一致。")
        hits: list[SearchHit] = []
        warnings: list[str] = []
        for index, entry in enumerate(entries[:limit], 1):
            title = _xml_text(entry, _ATOM + "title")
            raw_id = _xml_text(entry, _ATOM + "id")
            try:
                parsed = urlsplit(raw_id)
                source_id = parsed.path.removeprefix("/abs/") if parsed.path.startswith("/abs/") else ""
                valid_url = parsed.scheme in {"http", "https"} and parsed.hostname in {"arxiv.org", "www.arxiv.org"} and parsed.port in (None, 80, 443) and not parsed.query and not parsed.fragment and parsed.username is None and parsed.password is None
            except ValueError:
                valid_url = False
                source_id = ""
            arxiv_id = _arxiv_id(source_id) if valid_url else ""
            authors = [_xml_text(author, _ATOM + "name") for author in entry.findall(_ATOM + "author")]
            authors = [name for name in authors if name]
            published = _xml_text(entry, _ATOM + "published")
            try:
                year = datetime.fromisoformat(published.replace("Z", "+00:00")).year
            except ValueError:
                year = None
            if not title or not arxiv_id or not authors or year is None:
                warnings.append(f"arXiv 第 {index} 条记录缺少有效的标题、标识符、作者或发表日期，已跳过。")
                continue
            abstract = _xml_text(entry, _ATOM + "summary")
            if not abstract:
                warnings.append(f"arXiv {source_id} 未提供摘要。")
            raw_doi = _xml_text(entry, _ARXIV + "doi")
            doi = _doi(raw_doi)
            if raw_doi and not doi:
                warnings.append(f"arXiv {source_id} 的 DOI 格式无效，已忽略该标识符。")
            hits.append(SearchHit(
                paper=Paper(title=title, authors=authors, year=year, abstract=abstract, url=f"https://arxiv.org/abs/{source_id}", source=self.name),
                source_id=source_id, doi=doi, arxiv_id=arxiv_id, query=query,
                retrieved_at=response.retrieved_at, evidence=_evidence(response, self.name, source_id),
            ))
        return _finish(hits, warnings, len(entries[:limit]), self.name, response)


class SemanticScholarProvider:
    name = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, transport=None, *, api_key: str | None = None, timeout: float = 20.0, max_retries: int = 2, evidence_dir: str | Path | None = None):
        self.transport = transport if transport is not None else HttpTransport(timeout=timeout, max_retries=max_retries, evidence_dir=evidence_dir)
        self._api_key = api_key if api_key is not None else os.getenv("SEMANTIC_SCHOLAR_API_KEY", os.getenv("S2_API_KEY", ""))
        if not isinstance(self._api_key, str) or any(ord(char) < 32 or ord(char) >= 127 for char in self._api_key):
            raise ValueError("Semantic Scholar API key 必须为不含控制字符的 ASCII 字符串")

    def search(self, query: str, *, limit: int) -> ProviderResult:
        query = _validate_query(query, limit)
        request_url = self.endpoint + "?" + urlencode({
            "query": query,
            "limit": limit,
            "fields": "paperId,title,authors,year,abstract,url,externalIds",
        })
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        response = self.transport.get(request_url, headers=headers)
        try:
            payload = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise ProviderError("Semantic Scholar 返回了无法解析的 JSON 响应。") from None
        if not isinstance(payload, dict) or "error" in payload or "message" in payload:
            raise ProviderError("Semantic Scholar 返回了 API 错误或无效的结果对象。")
        data = payload.get("data")
        total = payload.get("total")
        if not isinstance(data, list) or isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ProviderError("Semantic Scholar 响应缺少有效的 data/total 字段。")
        if (total == 0 and data) or (total > 0 and not data):
            raise ProviderError("Semantic Scholar 响应的 total 与论文条目不一致。")
        hits: list[SearchHit] = []
        warnings: list[str] = []
        for index, item in enumerate(data[:limit], 1):
            if not isinstance(item, dict):
                warnings.append(f"Semantic Scholar 第 {index} 条记录不是对象，已跳过。")
                continue
            source_id, title = _text(item.get("paperId")), _text(item.get("title"))
            if not re.fullmatch(r"[a-fA-F0-9]{40}", source_id) or not title:
                warnings.append(f"Semantic Scholar 第 {index} 条记录缺少有效的 paperId 或标题，已跳过。")
                continue
            raw_authors = item.get("authors")
            if not isinstance(raw_authors, list):
                warnings.append(f"Semantic Scholar {source_id} 缺少有效的作者列表，已跳过。")
                continue
            authors = [_text(author.get("name")) for author in raw_authors if isinstance(author, dict)]
            authors = [name for name in authors if name]
            if len(authors) != len(raw_authors) or not authors:
                warnings.append(f"Semantic Scholar {source_id} 的作者信息不完整。")
            year = item.get("year")
            if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1000 <= year <= 9999):
                warnings.append(f"Semantic Scholar {source_id} 的年份无效，保留为未知。")
                year = None
            abstract = item.get("abstract")
            if abstract is not None and not isinstance(abstract, str):
                warnings.append(f"Semantic Scholar {source_id} 的摘要类型无效，保留为空。")
            abstract = _text(abstract)
            raw_url = _text(item.get("url"))
            try:
                parsed = urlsplit(raw_url)
                valid_url = parsed.scheme in {"http", "https"} and parsed.hostname in {"semanticscholar.org", "www.semanticscholar.org"} and bool(re.fullmatch(r"/paper/(?:[^/]+/)?[a-fA-F0-9]{40}", parsed.path)) and parsed.path.rsplit("/", 1)[-1].lower() == source_id.lower() and parsed.port in (None, 80, 443) and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment
            except ValueError:
                valid_url = False
            if valid_url:
                paper_url = "https://" + parsed.hostname + parsed.path
            else:
                paper_url = f"https://www.semanticscholar.org/paper/{source_id}"
                if raw_url:
                    warnings.append(f"Semantic Scholar {source_id} 的链接不是官方论文页，使用其真实 paperId 对应的官方地址。")
            external = item.get("externalIds")
            if not isinstance(external, dict):
                external = {}
            doi = _doi(external.get("DOI"))
            arxiv_id = _arxiv_id(external.get("ArXiv"))
            if external.get("DOI") and not doi:
                warnings.append(f"Semantic Scholar {source_id} 的 DOI 无效，已忽略。")
            if external.get("ArXiv") and not arxiv_id:
                warnings.append(f"Semantic Scholar {source_id} 的 arXiv ID 无效，已忽略。")
            hits.append(SearchHit(
                paper=Paper(title=title, authors=authors, year=year, abstract=abstract, url=paper_url, source=self.name),
                source_id=source_id, doi=doi, arxiv_id=arxiv_id, query=query,
                retrieved_at=response.retrieved_at, evidence=_evidence(response, self.name, source_id),
            ))
        return _finish(hits, warnings, len(data[:limit]), self.name, response)
