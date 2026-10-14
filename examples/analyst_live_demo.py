"""用 JSON 输入调用真实 Analyst；默认输入为三篇 MOCK_ONLY 模拟论文。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from research_assistant.agents.analyst import analyst_node


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(__file__).parent / "fixtures" / "analyst_mock.json")
    parser.add_argument("--output", type=Path, help="可选：保存分析结果为 JSON")
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        state = payload.get("state", payload)
        result = analyst_node(state)
        output = {
            "notice": "真实模型响应；输入论文来自指定 JSON 文件，默认样例为 MOCK_ONLY，不能当作真实科研证据。",
            "model": os.getenv("LLM_MODEL", ""),
            "api": os.getenv("LLM_API", "chat_completions"),
            **result,
        }
        encoded = json.dumps(output, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded + "\n", encoding="utf-8")
            print(f"分析完成，结果已保存：{args.output}")
        else:
            print(encoded)
    except Exception as exc:
        # 网关错误信息可能包含请求细节，不打印未经处理的完整 traceback。
        message = str(exc)
        key = os.getenv("OPENAI_API_KEY", "")
        if key:
            message = message.replace(key, "[REDACTED]")
        print(f"调用失败（{type(exc).__name__}）：{message[:1000]}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
