"""Internal retrieval records; public Paper keeps the team's seven fields."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..schemas import Paper


@dataclass
class SearchHit:
    paper: Paper
    source_id: str
    doi: str = ""
    arxiv_id: str = ""
    query: str = ""
    retrieved_at: str = ""
    # Request URL and response digest are evidence, never API keys or headers.
    evidence: dict = field(default_factory=dict)


@dataclass
class ProviderResult:
    hits: list[SearchHit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    response_evidence: dict = field(default_factory=dict)


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int) -> ProviderResult: ...


class ProviderError(RuntimeError):
    """A failed request or invalid upstream response, not an empty search."""

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}
