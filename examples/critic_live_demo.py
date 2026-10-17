"""读取 State JSON 调用正式 Critic；默认样例是模拟材料，响应来自真实模型。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from research_assistant.agents.critic import critic_node


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(__file__).parent / "fixtures" / "critic_mock.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("输入必须是 State JSON 对象或含 state 的封装")
        state = payload.get("state", payload.get("initial_state", payload))
        result = critic_node(state)
        output = {
            "notice": "正式 Critic；结构缺口可直接 FAIL，结构完整时调用真实模型。默认输入为 MOCK_ONLY，不是科研证据。",
            "model": os.getenv("LLM_MODEL", ""), "api": os.getenv("LLM_API", "chat_completions"), **result,
        }
        encoded = json.dumps(output, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded + "\n", encoding="utf-8")
            print(f"审核结果已保存：{args.output}")
        else:
            print(encoded)
    except Exception as exc:
        message = str(exc)
        key = os.getenv("OPENAI_API_KEY", "")
        if key:
            message = message.replace(key, "[REDACTED]")
        print(f"审核失败（{type(exc).__name__}）：{message[:1000]}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
