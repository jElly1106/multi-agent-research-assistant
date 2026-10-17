from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math


@dataclass(frozen=True)
class SearchConfig:
    """Bounded retrieval. top_k limits NEW papers per feedback round."""

    top_k: int = 10
    max_queries: int = 6
    results_per_query: int = 20
    year_from: int | None = None
    year_to: int | None = None
    min_relevance: float = 0.12
    required_keywords: tuple[str, ...] = ()
    excluded_keywords: tuple[str, ...] = ()
    keyword_match: str = "any"
    use_llm: bool = False
    sources: tuple[str, ...] = ("openalex",)
    timeout: float = 20
    max_retries: int = 2
    arxiv_proxy_mode: str = "auto"

    def __post_init__(self) -> None:
        for name, upper in (("top_k", 100), ("max_queries", 12), ("results_per_query", 100)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
                raise ValueError(f"{name} 必须是 1..{upper} 的整数")
        current_year = datetime.now(timezone.utc).year
        for name in ("year_from", "year_to"):
            year = getattr(self, name)
            if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1000 <= year <= current_year):
                raise ValueError(f"{name} 必须为 1000..{current_year} 的年份或 None")
        if self.year_from is not None and self.year_to is not None and self.year_from > self.year_to:
            raise ValueError("year_from 不能大于 year_to")
        if isinstance(self.min_relevance, bool) or not math.isfinite(self.min_relevance) or not 0 <= self.min_relevance <= 1:
            raise ValueError("min_relevance 必须在 0..1 之间")
        if self.keyword_match not in ("any", "all"):
            raise ValueError("keyword_match 必须为 any 或 all")
        if not isinstance(self.use_llm, bool):
            raise ValueError("use_llm 必须为 bool")
        if self.arxiv_proxy_mode not in {"auto", "direct", "system"}:
            raise ValueError("arxiv_proxy_mode 必须为 auto、direct 或 system")
        if not self.sources or len(set(self.sources)) != len(self.sources) or set(self.sources) - {"openalex", "arxiv", "semantic_scholar", "crossref"}:
            raise ValueError("sources 仅支持不重复的 openalex、arxiv、semantic_scholar、crossref")
        for name in ("required_keywords", "excluded_keywords"):
            words = getattr(self, name)
            if not isinstance(words, (list, tuple)) or any(not isinstance(w, str) or not w.strip() for w in words):
                raise ValueError(f"{name} 必须为非空字符串列表")
        if isinstance(self.timeout, bool) or not math.isfinite(self.timeout) or not 0 < self.timeout <= 120:
            raise ValueError("timeout 必须在 (0,120] 秒之间")
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int) or not 0 <= self.max_retries <= 3:
            raise ValueError("max_retries 必须为 0..3 的整数")

    @property
    def effective_year_to(self) -> int:
        return self.year_to or datetime.now(timezone.utc).year
