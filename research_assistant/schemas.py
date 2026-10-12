from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, HttpUrl


class CoordinatorOutput(BaseModel):
    """Coordinator 对研究主题拆解后的统一结构化输出。"""

    research_scope: str = Field(description="本次调研的边界、对象和重点")
    research_questions: list[str] = Field(description="需要回答的核心研究问题")
    search_directions: list[str] = Field(description="建议重点检索的方向")
    search_keywords: list[str] = Field(description="用于 Search Agent 的关键词/查询建议")
    research_plan: list[str] = Field(description="从检索到报告生成的任务计划")


class Paper(BaseModel):
    """Search Agent 输出给 Reader Agent 的统一论文格式。"""

    title: str
    authors: list[str]
    year: int | None = None
    abstract: str = ""
    url: str = ""
    source: str
    relevance_score: float | None = None


class PaperAnalysis(BaseModel):
    """Reader Agent 对单篇论文的结构化阅读结果。"""

    paper_title: str
    problem: str
    motivation: str
    method: str
    datasets: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    main_results: str = ""
    contributions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MethodCategory(BaseModel):
    name: str
    description: str = ""
    papers: list[str] = Field(default_factory=list)


class ResearchLandscape(BaseModel):
    """Method Analyst Agent 的统一输出。"""

    categories: list[MethodCategory] = Field(default_factory=list)
    comparison_table: list[dict[str, Any]] = Field(default_factory=list)
    evolution: list[str] = Field(default_factory=list)
    summary: str = ""


class CriticResult(BaseModel):
    """Critic Agent 的统一审核结果。"""

    decision: Literal["PASS", "FAIL"]
    feedback: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    missing_topics: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    new_search_queries: list[str] = Field(default_factory=list)


class FinalReport(BaseModel):
    title: str
    markdown: str
    references: list[str] = Field(default_factory=list)
