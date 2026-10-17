"""python -m examples.critic_mock_demo：离线执行正式 Critic 节点的反馈闭环。"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

from research_assistant.ablation import run_ablation
from research_assistant.agents.critic import create_critic_node


def load_fixture() -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / "critic_mock.json").read_text(encoding="utf-8"))


def make_node_factory(fixture: dict):
    """固定输入与预设模型响应；每组实验各建一套节点，无网络请求。"""
    def factory():
        initial = deepcopy(fixture["initial_state"])
        supplement = deepcopy(fixture["supplement"])
        model = Mock()
        model.invoke.side_effect = deepcopy(fixture["model_responses"])

        def search(state):
            papers = deepcopy(initial["papers"])
            if state.get("critic_result", {}).get("new_search_queries"):
                papers.append(deepcopy(supplement["paper"]))
            return {"papers": papers}

        def reader(state):
            analyses = deepcopy(initial["paper_analysis"])
            if len(state["papers"]) > 1:
                analyses.append(deepcopy(supplement["analysis"]))
            return {"paper_analysis": analyses}

        def analyst(state):
            landscape = deepcopy(initial["method_summary"])
            if len(state["paper_analysis"]) > 1:
                landscape["categories"].append(deepcopy(supplement["category"]))
                landscape["comparison_table"].append(deepcopy(supplement["comparison"]))
                landscape["summary"] = supplement["summary"]
            return {"method_summary": landscape}

        def writer(state):
            warning = "审核未完全通过\n" if state.get("termination_reason") == "max_critic_rounds" else ""
            return {"final_report": {
                "title": "MOCK_ONLY 对照报告",
                "markdown": warning + state["method_summary"]["summary"],
                "references": [p["title"] for p in state["papers"]],
            }}

        return dict(search_node=search, reader_node=reader, analyst_node=analyst,
                    critic_node=create_critic_node(model), writer_node=writer)
    return factory


def run_mock_ablation(fixture: dict) -> dict:
    # 只在本次调用期间关闭 Coordinator 的模型；不永久修改进程配置。
    from unittest.mock import patch
    with patch.dict("os.environ", {"COORDINATOR_USE_LLM": "0"}):
        return run_ablation(deepcopy(fixture["initial_state"]), make_node_factory(fixture))


def main() -> None:
    fixture = load_fixture()
    result = run_mock_ablation(fixture)["with_critic"]
    print(json.dumps({"notice": fixture["notice"], **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
