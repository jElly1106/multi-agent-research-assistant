"""Deterministic identity matching, filtering and explainable lexical scores."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from ..schemas import Paper
from .config import SearchConfig
from .keywords import clean_text, terms
from .models import SearchHit


ARXIV_ID = re.compile(r"(?:\d{4}\.\d{4,5}|[a-z][a-z.\-]+/\d{7})(?:v\d+)?", re.I)


def normalize_title(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def normalize_doi(value: str) -> str:
    value = unquote(value).strip().casefold()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)
    return value if re.fullmatch(r"10\.\d{4,9}/\S+", value) else ""


def normalize_arxiv(value: str) -> str:
    value = unquote(value).strip().lower()
    value = re.sub(r"^https?://(?:export\.)?arxiv\.org/(?:abs|pdf)/", "", value)
    value = re.sub(r"\.pdf$", "", value)
    return re.sub(r"v\d+$", "", value) if ARXIV_ID.fullmatch(value) else ""


def validate_paper(paper: Paper) -> Paper:
    """Validate a source URL shape. This alone does NOT prove a paper exists."""
    paper = paper.model_copy(deep=True)
    paper.title = clean_text(paper.title)
    if not paper.title or not paper.authors or any(not a.strip() for a in paper.authors):
        raise ValueError("论文 title/authors 必须为非空真实元数据")
    paper.authors = [clean_text(author) for author in paper.authors]
    paper.abstract = clean_text(paper.abstract)
    parsed = urlsplit(paper.url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.query or parsed.fragment:
        raise ValueError("论文 URL 必须为官方来源 HTTPS 地址")
    if paper.source == "arxiv":
        valid = parsed.hostname in {"arxiv.org", "export.arxiv.org"} and parsed.path.startswith("/abs/") and bool(normalize_arxiv(paper.url))
    elif paper.source == "semantic_scholar":
        valid = parsed.hostname in {"semanticscholar.org", "www.semanticscholar.org"} and bool(re.fullmatch(r"/paper/(?:[^/]+/)?[0-9a-fA-F]{40}", parsed.path))
    elif paper.source == "crossref":
        valid = parsed.hostname == "doi.org" and bool(normalize_doi(paper.url))
    elif paper.source == "openalex":
        valid = parsed.hostname == "openalex.org" and bool(re.fullmatch(r"/W[1-9]\d*", parsed.path))
    else:
        valid = False
    if not valid:
        raise ValueError("论文 source 与官方来源 URL 不匹配；不能输入 demo/stub 论文")
    if paper.relevance_score is not None and (not math.isfinite(paper.relevance_score) or not 0 <= paper.relevance_score <= 1):
        raise ValueError("relevance_score 必须在 0..1 之间")
    return paper


@dataclass
class Candidate:
    paper: Paper
    hits: list[SearchHit] = field(default_factory=list)
    existing: bool = False
    dois: set[str] = field(default_factory=set)
    arxiv_ids: set[str] = field(default_factory=set)
    source_ids: set[tuple[str, str]] = field(default_factory=set)
    score: float = 0.0
    score_details: dict = field(default_factory=dict)

    @classmethod
    def from_hit(cls, hit: SearchHit, *, existing: bool = False) -> "Candidate":
        paper = validate_paper(hit.paper)
        doi = normalize_doi(hit.doi) or (normalize_doi(paper.url) if paper.source == "crossref" else "")
        arxiv = normalize_arxiv(hit.arxiv_id) or normalize_arxiv(paper.url)
        return cls(paper=paper, hits=[hit], existing=existing,
                   dois={doi} if doi else set(), arxiv_ids={arxiv} if arxiv else set(),
                   source_ids={(paper.source, hit.source_id)} if hit.source_id else set())


def same_paper(a: Candidate, b: Candidate) -> bool:
    if a.dois & b.dois or a.arxiv_ids & b.arxiv_ids or a.source_ids & b.source_ids or a.paper.url == b.paper.url:
        return True
    # Different explicit identifiers are stronger than a similar title.
    if a.dois and b.dois and not a.dois & b.dois:
        return False
    if a.arxiv_ids and b.arxiv_ids and not a.arxiv_ids & b.arxiv_ids:
        return False
    if a.paper.year and b.paper.year and a.paper.year != b.paper.year:
        return False
    authors_a = {normalize_title(author) for author in a.paper.authors}
    authors_b = {normalize_title(author) for author in b.paper.authors}
    return normalize_title(a.paper.title) == normalize_title(b.paper.title) and bool(authors_a & authors_b)


def merge_candidate(target: Candidate, other: Candidate) -> None:
    # Already delivered titles are stable linkage keys for Reader/Analyst.
    if other.existing and not target.existing:
        target.paper, other.paper = other.paper, target.paper
    old, new = target.paper, other.paper
    if len(new.abstract) > len(old.abstract):
        old.abstract = new.abstract
    if len(new.authors) > len(old.authors):
        old.authors = list(new.authors)
    if old.year is None:
        old.year = new.year
    if not target.existing and not other.existing and new.source == "arxiv" and old.source != "arxiv":
        old.url, old.source = new.url, new.source
    target.existing |= other.existing
    target.dois.update(other.dois)
    target.arxiv_ids.update(other.arxiv_ids)
    target.source_ids.update(other.source_ids)
    target.hits.extend(other.hits)


def deduplicate(candidates: list[Candidate]) -> list[Candidate]:
    groups: list[Candidate] = []
    for candidate in candidates:
        matches = [group for group in groups if same_paper(group, candidate)]
        if not matches:
            groups.append(candidate)
            continue
        target = matches[0]
        merge_candidate(target, candidate)
        # A bridge record can join two previously disjoint source records.
        for match in matches[1:]:
            if same_paper(target, match):
                merge_candidate(target, match)
                groups.remove(match)
    return groups


def _phrase_matches(keyword: str, text: str) -> bool:
    # Explicit user filters must not silently lose words such as "model".
    tokens = terms(keyword, keep_stopwords=True)
    available = set(terms(text, keep_stopwords=True))
    return bool(tokens) and all(token in available for token in tokens)


def filter_reason(paper: Paper, config: SearchConfig) -> str | None:
    if paper.year is None:
        if config.year_from is not None or config.year_to is not None:
            return "year_unknown"
    elif paper.year < 1000 or paper.year > config.effective_year_to or (config.year_from is not None and paper.year < config.year_from):
        return "year_out_of_range"
    text = paper.title + " " + paper.abstract
    if any(_phrase_matches(keyword, text) for keyword in config.excluded_keywords):
        return "excluded_keyword"
    if config.required_keywords:
        matches = [_phrase_matches(keyword, text) for keyword in config.required_keywords]
        if not (all(matches) if config.keyword_match == "all" else any(matches)):
            return "required_keyword_missing"
    return None


def relevance(candidate: Candidate, *, topic: str, queries: list[str]) -> float:
    title_tokens = set(terms(candidate.paper.title))
    abstract_tokens = set(terms(candidate.paper.abstract))

    def coverage(query: str) -> float:
        tokens = set(terms(query))
        if not tokens:
            return 0.0
        # Title matches receive full credit, abstract-only matches receive 0.7.
        return sum(1.0 if t in title_tokens else 0.7 if t in abstract_tokens else 0.0 for t in tokens) / len(tokens)

    topic_coverage = coverage(topic)
    query_coverages = [coverage(query) for query in queries]
    best_query = max(query_coverages, default=0.0)
    score = round(0.65 * topic_coverage + 0.35 * best_query, 6)
    candidate.score = score
    candidate.score_details = {"topic_coverage": round(topic_coverage, 6), "best_query_coverage": round(best_query, 6),
                               "matched_terms": sorted((title_tokens | abstract_tokens) & set(terms(topic + " " + " ".join(queries)))),
                               "formula": "0.65 * topic_coverage + 0.35 * best_query_coverage; title=1, abstract_only=0.7"}
    candidate.paper.relevance_score = score
    return score


def validate_paper_references(references: list[str], papers: list[dict]) -> None:
    """A downstream membership guard; it does not validate a scientific claim."""
    allowed: set[str] = set()
    for data in papers:
        paper = validate_paper(Paper.model_validate(data))
        allowed.update((paper.title.strip(), paper.url))
    if not isinstance(references, list) or any(not isinstance(r, str) or r.strip() not in allowed for r in references):
        raise ValueError("引用包含 Search 论文列表之外的标题或 URL")
