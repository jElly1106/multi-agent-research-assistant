from __future__ import annotations

from typing import Any, Callable, Literal

from langgraph.graph import END, START, StateGraph

from .agents.coordinator import coordinator_node
from .state import ResearchState

Node = Callable[[ResearchState], dict[str, Any]]


def _with_critic_round(critic_node: Node) -> Node:
    """给成员5的 Critic 节点加一层统一的循环计数，不要求成员5自己处理。"""

    def wrapped(state: ResearchState) -> dict[str, Any]:
        result = critic_node(state) or {}
        current_round = int(state.get("critic_round", 0)) + 1
        result["critic_round"] = current_round

        critic_result = result.get("critic_result") or state.get("critic_result") or {}
        decision = str(critic_result.get("decision", "FAIL")).upper()
        max_rounds = int(state.get("max_critic_rounds", 2))
        if decision != "PASS" and current_round >= max_rounds:
            result["termination_reason"] = "max_critic_rounds"
        return result

    return wrapped


def route_after_critic(state: ResearchState) -> Literal["search", "writer"]:
    """Critic PASS -> Writer；FAIL -> Search；超过最大轮次则强制进入 Writer 并保留警告。"""
    critic = state.get("critic_result") or {}
    decision = str(critic.get("decision", "FAIL")).upper()
    if decision == "PASS":
        return "writer"

    current_round = int(state.get("critic_round", 0))
    max_rounds = int(state.get("max_critic_rounds", 2))
    if current_round >= max_rounds:
        return "writer"
    return "search"


def build_research_graph(
    *,
    search_node: Node,
    reader_node: Node,
    analyst_node: Node,
    critic_node: Node,
    writer_node: Node,
):
    """构建成员1负责的 LangGraph 总体架构。

    其他成员只需要把自己的 Agent 函数按 Node 签名传进来即可：
        node(state: ResearchState) -> dict[str, Any]
    """
    graph = StateGraph(ResearchState)

    graph.add_node("coordinator", coordinator_node)
    graph.add_node("search", search_node)
    graph.add_node("reader", reader_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("critic", _with_critic_round(critic_node))
    graph.add_node("writer", writer_node)

    graph.add_edge(START, "coordinator")
    graph.add_edge("coordinator", "search")
    graph.add_edge("search", "reader")
    graph.add_edge("reader", "analyst")
    graph.add_edge("analyst", "critic")

    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "search": "search",
            "writer": "writer",
        },
    )
    graph.add_edge("writer", END)

    return graph.compile()
