"""成员5：可追溯的系统指标；未知事实保持 null，不能用 URL 存在代替核验。"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .schemas import CriticResult, FinalReport, Paper
from .state import ResearchState


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PaperJudgment(Annotation):
    title: str
    is_real: bool | None = None
    is_valid: bool | None = None
    note: str = ""


class CitationJudgment(Annotation):
    reference: str
    correct: bool
    note: str = Field(min_length=1, description="独立核验的依据，包含论文存在性及引用是否支持结论")


class QuestionJudgment(Annotation):
    question: str
    covered: bool
    evidence: str = ""


class EvaluationAnnotations(Annotation):
    papers: list[PaperJudgment] = Field(default_factory=list)
    citations: list[CitationJudgment] = Field(default_factory=list)
    questions: list[QuestionJudgment] = Field(default_factory=list)


def normalize_title(title: str) -> str:
    """只合并大小写、Unicode 与空白差异；不猜测近似标题是否同一论文。"""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", title)).strip().casefold()


def _index(items: list[Any], field: str, allowed: set[str]) -> dict[str, Any]:
    result = {}
    for item in items:
        key = normalize_title(getattr(item, field))
        if not key or key not in allowed:
            raise ValueError(f"评价标注不对应当前输入的 {field}：{getattr(item, field)}")
        if key in result:
            raise ValueError(f"评价标注重复：{getattr(item, field)}")
        result[key] = item
    return result


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def evaluate_run(
    state: ResearchState,
    annotations: EvaluationAnnotations | dict[str, Any] | None = None,
    *,
    critic_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """评价最终快照。人工/独立审阅器提供事实和覆盖标注；不自动访问论文数据库。"""
    if not isinstance(state, dict):
        raise ValueError("State 必须是 JSON 对象")
    if not isinstance(state.get("papers", []), list):
        raise ValueError("papers 必须是列表")
    if critic_history is not None and not isinstance(critic_history, list):
        raise ValueError("critic_history 必须是完整的审核结果数组")
    labels = EvaluationAnnotations.model_validate(annotations if annotations is not None else {})
    papers = [Paper.model_validate(p) for p in state.get("papers", [])]
    paper_counts = Counter(normalize_title(p.title) for p in papers)
    if "" in paper_counts:
        raise ValueError("论文标题不能为空")
    paper_labels = _index(labels.papers, "title", set(paper_counts))
    for label in paper_labels.values():
        if label.is_real is False and label.is_valid is True:
            raise ValueError("不存在的论文不能标为有效")
        if (label.is_real is not None or label.is_valid is not None) and not label.note.strip():
            raise ValueError("论文核验标注必须提供 note")
    # 同一标题元数据冲突时拒绝按一个标注自动评判两个版本。
    unique_papers: dict[str, Paper] = {}
    for paper in papers:
        key = normalize_title(paper.title)
        if key in unique_papers:
            previous = unique_papers[key].model_dump(exclude={"title"})
            if previous != paper.model_dump(exclude={"title"}):
                raise ValueError(f"同标题论文元数据冲突：{paper.title}")
        unique_papers[key] = paper

    report = state.get("final_report")
    if isinstance(report, dict):
        parsed = FinalReport.model_validate(report)
        markdown, references = parsed.markdown, parsed.references
    elif isinstance(report, str):
        markdown, references = report, []
    elif report is None:
        markdown, references = "", []
    else:
        raise ValueError("final_report 必须是对象或字符串")
    reference_keys = [normalize_title(r) for r in references]
    if any(not r for r in reference_keys):
        raise ValueError("报告引用不能为空")
    unique_references = set(reference_keys)
    citation_labels = _index(labels.citations, "reference", unique_references)
    if any(not label.note.strip() for label in citation_labels.values()):
        raise ValueError("引用核验标注必须提供 note")
    questions = state.get("research_questions", [])
    if not isinstance(questions, list) or any(not isinstance(q, str) or not q.strip() for q in questions):
        raise ValueError("research_questions 必须是非空字符串列表")
    question_keys = {normalize_title(q) for q in questions}
    question_labels = _index(labels.questions, "question", question_keys)
    for label in question_labels.values():
        if label.covered and (not label.evidence.strip() or label.evidence not in markdown):
            raise ValueError("标为已覆盖的问题必须附报告中的精确证据摘录")

    history = None if critic_history is None else [CriticResult.model_validate(r) for r in critic_history]
    rounds = state.get("critic_round", 0)
    if type(rounds) is not int or rounds < 0:
        raise ValueError("critic_round 必须是非负整数")
    if history is not None and "critic_round" in state and len(history) != rounds:
        raise ValueError("critic_history 长度与 critic_round 不一致，须提供完整历史")
    validity = [p.is_valid for p in paper_labels.values() if p.is_valid is not None]
    reality = [p.is_real for p in paper_labels.values() if p.is_real is not None]
    correct = sum(p.correct for p in citation_labels.values())
    covered = sum(p.covered for p in question_labels.values())
    unique_count = len(paper_counts)
    return {
        "paper_count": len(papers),
        "unique_paper_count": unique_count,
        "duplicate_count": len(papers) - unique_count,
        "duplicate_rate": _ratio(len(papers) - unique_count, len(papers)),
        "verified_real_paper_count": sum(reality),
        "reality_judged_count": len(reality),
        "reality_judgment_coverage": _ratio(len(reality), unique_count),
        "invalid_paper_count": validity.count(False),
        "validity_judged_count": len(validity),
        "invalid_paper_ratio": _ratio(validity.count(False), len(validity)),
        "validity_judgment_coverage": _ratio(len(validity), unique_count),
        "unique_reference_count": len(unique_references),
        "reference_traceability_rate": _ratio(len(unique_references & set(paper_counts)), len(unique_references)),
        "citation_judged_count": len(citation_labels),
        "citation_correctness_rate": _ratio(correct, len(citation_labels)),
        "citation_judgment_coverage": _ratio(len(citation_labels), len(unique_references)),
        "critic_invocations": len(history) if history is not None else rounds,
        "critic_fail_count": sum(r.decision == "FAIL" for r in history) if history is not None else None,
        "question_count": len(question_keys),
        "question_judged_count": len(question_labels),
        "covered_question_count": covered,
        "report_coverage_rate": _ratio(covered, len(question_keys)) if len(question_labels) == len(question_keys) else None,
        "question_judgment_coverage": _ratio(len(question_labels), len(question_keys)),
        "termination_reason": state.get("termination_reason", ""),
    }


def compare_runs(without: dict[str, Any], with_critic: dict[str, Any]) -> dict[str, Any]:
    """保留原始指标；只对双方均已测量的数值计算 with - without。"""
    delta = {
        key: with_critic[key] - value
        for key, value in without.items()
        if type(value) in (int, float) and type(with_critic.get(key)) in (int, float)
    }
    return {"without_critic": without, "with_critic": with_critic, "delta_with_minus_without": delta}
