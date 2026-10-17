"""评价已保存的 State：--input state.json [--annotations labels.json] [--history history.json]。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_assistant.evaluation import evaluate_run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--history", type=Path, help="按时间排序的 critic_result 对象数组")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("输入必须是 State 对象或含 state 的封装")
        state = payload.get("state", payload)
        labels = json.loads(args.annotations.read_text(encoding="utf-8-sig")) if args.annotations else None
        history = json.loads(args.history.read_text(encoding="utf-8-sig")) if args.history else payload.get("critic_history")
        if history is not None and not isinstance(history, list):
            raise ValueError("history 必须是数组")
        result = evaluate_run(state, labels, critic_history=history)
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded + "\n", encoding="utf-8")
        else:
            print(encoded)
    except (ValueError, OSError, TypeError) as exc:
        parser.exit(1, f"评价失败：{exc}\n")


if __name__ == "__main__":
    main()
