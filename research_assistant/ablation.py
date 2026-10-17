"""在相同初始 State 上执行有/无 Critic 的成对实验。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from .graph import Node, build_research_graph
from .agents.coordinator import coordinator_node
from .schemas import CriticResult
from .state import ResearchState


def run_ablation(
    initial_state: ResearchState,
    node_factory: Callable[[], dict[str, Node]],
) -> dict[str, Any]:
    """每组重新创建节点与输入，隔离模型 mock 序列/缓存等可变状态。

    factory 返回 search_node/reader_node/analyst_node/critic_node/writer_node。
    Without 组用 PASS 路由适配器跳过实际 Critic，历史记录为空，不计一次虚假审核。
    使用真实节点时会实际请求服务、消耗费用。随机模型应固定配置并进行多次成对实验。
    """
    # 规划只生成一次，避免随机 Coordinator 把两组变成不同研究任务。
    prepared = deepcopy(initial_state)
    if not prepared.get("research_questions"):
        prepared.update(coordinator_node(prepared))
    plan = {key: deepcopy(prepared[key]) for key in (
        "research_scope", "research_questions", "search_directions", "search_keywords", "research_plan"
    ) if key in prepared}
    outputs: dict[str, Any] = {}
    for arm in ("without_critic", "with_critic"):
        nodes = dict(node_factory())
        actual_critic = nodes.pop("critic_node")
        history: list[dict[str, Any]] = []

        def review(state: ResearchState) -> dict[str, Any]:
            if arm == "without_critic":
                return {"critic_result": CriticResult(decision="PASS").model_dump()}
            result = actual_critic(state)
            history.append(deepcopy(CriticResult.model_validate(result["critic_result"]).model_dump()))
            return result

        graph = build_research_graph(**nodes, critic_node=review, coordinator=lambda state: deepcopy(plan))
        start = deepcopy(prepared)
        for key in ("critic_result", "critic_round", "termination_reason", "final_report"):
            start.pop(key, None)
        start["critic_round"] = 0
        result = graph.invoke(start)
        if arm == "without_critic":
            # PASS 只是 Graph 的路由适配值，不能作为已经审核的结果交付。
            result.pop("critic_result", None)
            result["critic_round"] = 0
        outputs[arm] = {"state": result, "critic_history": history, "critic_bypassed": arm == "without_critic"}
    return outputs
