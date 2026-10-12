"""仅用于成员1独立演示 Graph 是否能跑通。

这些 stub 不是成员2~6的正式实现，也绝对不能作为最终系统的论文数据来源。
"""
from __future__ import annotations

from typing import Any

from .state import ResearchState


def demo_search_node(state: ResearchState) -> dict[str, Any]:
    return {
        "papers": [
            {
                "title": "DEMO_ONLY: synthetic paper for graph integration",
                "authors": ["Demo Author"],
                "year": 2026,
                "abstract": "Synthetic placeholder. Replace with Search Agent real results.",
                "url": "",
                "source": "DEMO_ONLY",
                "relevance_score": 1.0,
            }
        ]
    }


def demo_reader_node(state: ResearchState) -> dict[str, Any]:
    title = state.get("papers", [{}])[0].get("title", "DEMO_ONLY")
    return {
        "paper_analysis": [
            {
                "paper_title": title,
                "problem": "DEMO_ONLY",
                "motivation": "DEMO_ONLY",
                "method": "DEMO_ONLY",
                "datasets": [],
                "metrics": [],
                "main_results": "DEMO_ONLY",
                "contributions": ["DEMO_ONLY"],
                "limitations": ["DEMO_ONLY"],
            }
        ]
    }


def demo_analyst_node(state: ResearchState) -> dict[str, Any]:
    return {
        "method_summary": {
            "categories": [],
            "comparison_table": [],
            "evolution": [],
            "summary": "DEMO_ONLY: analyst stub",
        }
    }


def demo_critic_node(state: ResearchState) -> dict[str, Any]:
    # 仅测试 PASS 路由；正式版本由成员5实现证据检查。
    return {
        "critic_result": {
            "decision": "PASS",
            "feedback": ["DEMO_ONLY: routing test passed"],
            "evidence_gaps": [],
            "missing_topics": [],
            "unsupported_claims": [],
            "new_search_queries": [],
        }
    }


def demo_writer_node(state: ResearchState) -> dict[str, Any]:
    warning = ""
    if state.get("termination_reason") == "max_critic_rounds":
        warning = "\n\n> Warning: Critic 未通过且达到最大反馈轮次。"
    return {
        "final_report": {
            "title": f"DEMO_ONLY - {state.get('topic', '')}",
            "markdown": "# DEMO_ONLY\n仅用于验证成员1的 LangGraph 编排。" + warning,
            "references": [],
        }
    }
