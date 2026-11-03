"""Member 6 application service: explicit demo/live modes, streamed graph updates."""
from __future__ import annotations

from copy import deepcopy
import os

from .agents.writer import create_writer_node
from .graph import build_research_graph

NODES = ("coordinator", "search", "reader", "analyst", "critic", "writer")
LABELS = dict(zip(NODES, ("研究规划", "文献检索", "结构化阅读", "方法分析", "证据审核", "报告生成")))


def model_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip() and os.getenv("LLM_MODEL", "").strip())


def build_app(*, mode="demo", top_k=3, max_queries=1, sources=("openalex",), on_reader_result=None):
    if mode == "demo":
        import json
        from pathlib import Path
        from .agents.analyst import create_analyst_node
        from .demo_stubs import demo_critic_node
        fixture = json.loads((Path(__file__).parents[1]/"examples/fixtures/analyst_mock.json").read_text("utf-8"))
        sample = fixture["state"]

        class SyntheticModel:
            def invoke(self, messages):
                return deepcopy(fixture["model_response"])

        def coordinator(state):
            # Do not consult keys or process-global model switches in offline demonstration.
            return {"research_scope": "仅验证编排和页面功能，全部论文和阅读结果为人工构造。",
                    "research_questions": deepcopy(sample["research_questions"]),
                    "search_keywords": [state["topic"]], "search_directions": [], "research_plan": list(LABELS.values())}

        return build_research_graph(coordinator=coordinator,
                                    search_node=lambda state: {"papers": deepcopy(sample["papers"])},
                                    reader_node=lambda state: {"paper_analysis": deepcopy(sample["paper_analysis"])},
                                    analyst_node=create_analyst_node(SyntheticModel()),
                                    critic_node=demo_critic_node, writer_node=create_writer_node(use_llm=False))
    if mode != "live":
        raise ValueError("模式必须为 demo 或 live")
    if not model_configured():
        raise RuntimeError("真实运行需要 OPENAI_API_KEY 和 LLM_MODEL")
    if os.getenv("READER_USE_LLM", "1").strip() == "0" or os.getenv("COORDINATOR_USE_LLM", "1").strip() == "0":
        raise RuntimeError("真实运行需要启用 Coordinator 和 Reader 的模型开关")
    from .agents.search import create_search_node
    from .search.config import SearchConfig
    from .reader_node import create_fulltext_reader_node
    from .agents.analyst import analyst_node
    from .agents.critic import critic_node
    return build_research_graph(search_node=create_search_node(config=SearchConfig(
        top_k=top_k, max_queries=max_queries, results_per_query=5, sources=tuple(sources), max_retries=0)),
        reader_node=create_fulltext_reader_node(download_arxiv=True,
            download_options={"resolve_openalex": True}, on_result=on_reader_result),
        analyst_node=analyst_node, critic_node=critic_node,
        writer_node=create_writer_node())


def stream_research(topic, *, mode="demo", max_critic_rounds=2, graph=None, **options):
    topic = topic.strip()
    if not topic:
        raise ValueError("请输入研究主题")
    if type(max_critic_rounds) is not int or not 1 <= max_critic_rounds <= 5:
        raise ValueError("审核轮次必须是 1 到 5 的整数")
    reader_diagnostics = []

    def collect_reader_result(result):
        acquisitions = {r["paper_title"]: r for r in result.get("acquisition", [])}
        reader_diagnostics.clear()
        for detail in result["details"]:
            title = detail["paper_title"]
            reader_diagnostics.append({"paper_title": title, "status": detail["status"],
                "processed_chunks": detail["processed_chunks"],
                "field_sources": deepcopy(detail["field_sources"]),
                "issues": [i["code"] for i in detail["issues"]],
                "acquisition": deepcopy(acquisitions.get(title, {})),
                "budget_denials": [e["code"] for e in result["budget"]["events"]
                                   if e["paper_title"] == title and not e["admitted"]]})

    app = graph if graph is not None else build_app(
        mode=mode, on_reader_result=collect_reader_result, **options)
    state = {"topic": topic, "critic_round": 0, "max_critic_rounds": max_critic_rounds}
    # Each round has four repeatable nodes, plus Coordinator and Writer.
    for update in app.stream(deepcopy(state), stream_mode="updates",
                             config={"recursion_limit": 4 * max_critic_rounds + 10}):
        for name, fields in update.items():
            if name not in NODES or not isinstance(fields, dict):
                continue
            state.update(fields)
            event = {"node": name, "state": deepcopy(state), "mode": mode}
            if name == "reader" and reader_diagnostics:
                event["reader_diagnostics"] = deepcopy(reader_diagnostics)
            yield event
