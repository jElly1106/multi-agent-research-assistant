"""Member 2 Search node: real API results -> the existing Paper contract."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from typing import Any

from ..schemas import Paper
from ..state import ResearchState
from ..search.config import SearchConfig
from ..search.keywords import generate_queries
from ..search.models import ProviderError, SearchHit, SearchProvider
from ..search.ranking import Candidate, deduplicate, filter_reason, relevance, validate_paper_references


class SearchUnavailableError(RuntimeError):
    """Every API request failed; an outage must not look like zero results."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SearchAgent:
    def __init__(self, *, config: SearchConfig | None = None, providers: list[SearchProvider] | None = None,
                 keyword_model: Any = None, audit_dir: str | Path | None = None):
        self.config = config or SearchConfig()
        self.keyword_model = keyword_model
        self.audit_dir = Path(audit_dir) if audit_dir is not None else None
        if providers is None:
            from ..search.providers import ArxivProvider, SemanticScholarProvider
            from ..search.crossref import CrossrefProvider
            from ..search.openalex import OpenAlexProvider
            constructors = {"openalex": OpenAlexProvider, "arxiv": ArxivProvider, "semantic_scholar": SemanticScholarProvider, "crossref": CrossrefProvider}
            self.providers = [constructors[name](timeout=self.config.timeout, max_retries=self.config.max_retries,
                              evidence_dir=self.audit_dir / "raw" if self.audit_dir else None,
                              **({"proxy_mode": self.config.arxiv_proxy_mode} if name == "arxiv" else {})) for name in self.config.sources]
        else:
            if not providers or any(p.name not in {"openalex", "arxiv", "semantic_scholar", "crossref"} for p in providers):
                raise ValueError("providers 必须包含受支持的检索来源")
            self.providers = list(providers)
        self.last_audit: dict[str, Any] = {}
        self._known_hits: dict[str, list[SearchHit]] = {}

    def _save_audit(self) -> None:
        if self.audit_dir is not None:
            self.audit_dir.mkdir(parents=True, exist_ok=True)
            path = self.audit_dir / (self.last_audit["run_id"] + ".json")
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.last_audit, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            temporary.replace(path)

    def __call__(self, state: ResearchState) -> dict[str, Any]:
        config = self.config
        queries, warnings = generate_queries(state, max_queries=config.max_queries,
                                             model=self.keyword_model, use_llm=config.use_llm)
        existing = state.get("papers", [])
        if not isinstance(existing, list):
            raise ValueError("ResearchState.papers 必须为论文列表")
        candidates: list[Candidate] = []
        # Treat restored State as trusted Search output, never as a model suggestion.
        # Its official URL format is checked; a fresh API request is not implied.
        for data in existing:
            paper = Paper.model_validate(data)
            known = self._known_hits.get(paper.url)
            if known:
                candidate = Candidate.from_hit(SearchHit(paper, "", evidence={"kind": "existing_state"}), existing=True)
                for hit in known:
                    enriched = Candidate.from_hit(hit)
                    candidate.dois.update(enriched.dois)
                    candidate.arxiv_ids.update(enriched.arxiv_ids)
                    candidate.source_ids.update(enriched.source_ids)
                candidate.hits = list(known)
            else:
                candidate = Candidate.from_hit(SearchHit(paper, "", evidence={"kind": "existing_state", "api_reverified": False}), existing=True)
            candidates.append(candidate)
        if existing and any(c.hits[0].evidence.get("kind") == "existing_state" for c in candidates):
            warnings.append("部分已有论文来自恢复的 State：已校验来源 URL 格式，本轮未重新验证其原始 API 证据，请保留上轮 audit")

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        audit: dict[str, Any] = {"run_id": run_id, "started_at": _now(), "topic": state["topic"],
             "config": asdict(config), "queries": queries, "requests": [], "warnings": warnings,
             "counts": {"existing_input": len(existing), "api_records": 0, "api_hits": 0, "invalid_hits": 0},
             "candidates": [], "papers": [], "status": "running"}
        self.last_audit = audit
        successes = 0
        failed_providers: set[str] = set()
        # Query first: Critic queries reach every source before lower-priority queries.
        # A failed source is skipped for the rest of this round (bounded retry/circuit breaker).
        for query in queries:
            for provider in self.providers:
                if provider.name in failed_providers:
                    continue
                request_info = {"source": provider.name, "query": query}
                try:
                    result = provider.search(query, limit=config.results_per_query)
                except (ProviderError, TimeoutError, ConnectionError, OSError) as exc:
                    # Adapter error strings must be sanitized. Other injected clients may not be.
                    detail = str(exc) if isinstance(exc, ProviderError) else type(exc).__name__
                    message = f"{provider.name} 检索失败：{detail}"
                    warnings.append(message)
                    request_info.update(status="failed", error=message)
                    if isinstance(exc, ProviderError) and exc.details:
                        request_info["failure_evidence"] = exc.details
                    failed_providers.add(provider.name)
                else:
                    successes += 1
                    warnings.extend(result.warnings)
                    audit["counts"]["api_hits"] += len(result.hits)
                    audit["counts"]["api_records"] += result.response_evidence.get("raw_record_count", len(result.hits))
                    request_info.update(status="success", hits=len(result.hits))
                    request_info["response_evidence"] = result.response_evidence
                    valid_hits = 0
                    for hit in result.hits:
                        try:
                            if hit.paper.source != provider.name:
                                raise ValueError("来源与当前适配器不匹配")
                            # Query is transport context, not paper metadata.
                            if not hit.query:
                                hit.query = query
                            candidates.append(Candidate.from_hit(hit))
                            valid_hits += 1
                        except (ValueError, TypeError):
                            audit["counts"]["invalid_hits"] += 1
                            warnings.append(f"{provider.name} 返回的论文记录未通过来源/格式校验，已排除")
                    if result.hits and not valid_hits:
                        successes -= 1
                        failed_providers.add(provider.name)
                        request_info.update(status="invalid_results", error="所有返回记录均未通过来源/格式校验")
                        warnings.append(f"{provider.name} 全部返回记录无效，不能视为正常的零条结果")
                audit["requests"].append(request_info)
        if not successes:
            audit.update(status="unavailable", finished_at=_now())
            self._save_audit()
            if any(r.get("failure_evidence", {}).get("rate_limited") for r in audit["requests"]):
                raise SearchUnavailableError("论文 API 请求收到 HTTP 429 限流响应，本轮已停止；请查看审计中的等待建议，暂勿连续重跑。未生成任何替代论文。")
            raise SearchUnavailableError("全部文献检索来源不可用；请查看 audit/errors 并重试，未生成任何替代论文")

        groups = deduplicate(candidates)
        audit["counts"]["source_discarded"] = audit["counts"]["api_records"] - audit["counts"]["api_hits"]
        audit["counts"]["duplicates_removed"] = len(candidates) - len(groups)
        audit["counts"]["unique_candidates"] = len(groups)
        accepted: list[Candidate] = []
        kept_existing: list[Candidate] = []
        filtered: dict[str, int] = {}
        for candidate in groups:
            score = relevance(candidate, topic=state["topic"], queries=queries)
            reason = filter_reason(candidate.paper, config)
            # Earlier selected papers remain available during Critic supplementation.
            if reason is None and not candidate.existing and score < config.min_relevance:
                reason = "low_relevance"
            if reason:
                filtered[reason] = filtered.get(reason, 0) + 1
            elif candidate.existing:
                kept_existing.append(candidate)
            else:
                accepted.append(candidate)
            record = {"paper": candidate.paper.model_dump(mode="json"), "existing": candidate.existing,
                "score": score, "score_details": candidate.score_details, "filter_reason": reason,
                "identifiers": {"dois": sorted(candidate.dois), "arxiv_ids": sorted(candidate.arxiv_ids)},
                "provenance": [{"source": h.paper.source, "source_id": h.source_id, "url": h.paper.url,
                                "query": h.query, "retrieved_at": h.retrieved_at, **h.evidence} for h in candidate.hits]}
            audit["candidates"].append(record)
        accepted.sort(key=lambda c: (-c.score, -(c.paper.year or 0), c.paper.title.casefold(), c.paper.url))
        selected = kept_existing + accepted[:config.top_k]
        papers = [candidate.paper.model_dump(mode="json") for candidate in selected]
        titles = [paper["title"] for paper in papers]
        if len(set(titles)) != len(titles):
            warnings.append("存在同标题但不同标识符的论文：未错误合并，请下游结合 URL 区分；当前 Analyst 的标题关联可能需要人工处理")
        selected_urls = {paper["url"] for paper in papers}
        for record in audit["candidates"]:
            record["selected"] = record["paper"]["url"] in selected_urls
            if record["filter_reason"] is None and not record["selected"]:
                record["filter_reason"] = "outside_top_k"
        if filtered and any(c.existing and filter_reason(c.paper, config) for c in groups):
            warnings.append("已有论文不符合本轮显式年份/关键词条件，已排除；原记录仍保留在 audit")
        if not papers:
            warnings.append("检索成功但没有符合筛选条件的论文；请调整关键词、年份或分数阈值")
        audit["counts"].update(filtered=filtered, new_selected=min(len(accepted), config.top_k),
                               existing_retained=len(kept_existing), returned=len(papers),
                               outside_top_k=max(0, len(accepted) - config.top_k))
        audit.update(status="partial" if failed_providers else "success", papers=papers, finished_at=_now())
        self._save_audit()
        for candidate in selected:
            self._known_hits[candidate.paper.url] = list(candidate.hits)
        result: dict[str, Any] = {"papers": papers}
        if warnings:
            result["errors"] = list(state.get("errors") or []) + list(dict.fromkeys(warnings))
        return result


def create_search_node(*, config: SearchConfig | None = None, providers: list[SearchProvider] | None = None,
                       keyword_model: Any = None, audit_dir: str | Path | None = None) -> SearchAgent:
    return SearchAgent(config=config, providers=providers, keyword_model=keyword_model, audit_dir=audit_dir)


def search_node(state: ResearchState) -> dict[str, Any]:
    """Default node; use the factory to configure filters or preserve audit files."""
    return create_search_node()(state)


__all__ = ["SearchConfig", "SearchAgent", "SearchUnavailableError", "create_search_node", "search_node", "validate_paper_references"]
