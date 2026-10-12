from __future__ import annotations

from typing import Any, TypedDict


class ResearchState(TypedDict, total=False):
    """整个 Multi-Agent Workflow 共享的 State。

    约定：所有 Agent 只返回自己负责更新的字段；未修改字段由 LangGraph 保留。
    为方便跨成员联调，跨 Agent 的复杂对象使用可 JSON 序列化的 dict/list。
    """

    # 用户输入 / Coordinator 输出
    topic: str
    research_scope: str
    research_questions: list[str]
    search_directions: list[str]
    search_keywords: list[str]
    research_plan: list[str]

    # Search Agent 输出
    papers: list[dict[str, Any]]

    # Reader Agent 输出
    paper_analysis: list[dict[str, Any]]

    # Method Analyst Agent 输出
    method_summary: dict[str, Any]

    # Critic Agent 输出 + 反馈循环控制
    critic_result: dict[str, Any]
    critic_round: int
    max_critic_rounds: int
    termination_reason: str

    # Writer Agent 输出
    final_report: dict[str, Any] | str

    # 可选调试/错误信息
    errors: list[str]
