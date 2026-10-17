"""python -m examples.critic_ablation_demo --output output/critic_ablation.json"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from examples.critic_mock_demo import load_fixture, run_mock_ablation
from research_assistant.evaluation import compare_runs, evaluate_run


def mock_annotations(fixture: dict, arm: str) -> dict:
    """预先定义的合成标注，独立于模型的 PASS/FAIL；不得当作真实人工评测。"""
    improved = arm == "with_critic"
    titles = ["MOCK_ONLY A", "MOCK_ONLY B"] if improved else ["MOCK_ONLY A"]
    questions = fixture["initial_state"]["research_questions"]
    return {
        "papers": [{"title": title, "is_real": False, "is_valid": False, "note": "人工构造的测试论文。"} for title in titles],
        "citations": [{"reference": title, "correct": False, "note": "引用虽可追溯到模拟输入，但论文不真实，不能计为真实正确引用。"} for title in titles],
        "questions": [
            {"question": questions[0], "covered": True, "evidence": "样本 A 采用 Cross Attention"},
            {"question": questions[1], "covered": improved, "evidence": "局限：A 仅测试一个模拟数据集；B 未测试文本缺失。" if improved else ""},
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    fixture = load_fixture()
    runs = run_mock_ablation(fixture)
    metrics = {arm: evaluate_run(run["state"], mock_annotations(fixture, arm),
                                 critic_history=run["critic_history"]) for arm, run in runs.items()}
    output = {"notice": fixture["notice"], "experiment": "paired scripted synthetic demonstration",
              "metrics": compare_runs(metrics["without_critic"], metrics["with_critic"]), "runs": runs}
    encoded = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(f"模拟消融结果已保存：{args.output}")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
