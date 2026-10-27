"""python -m research_assistant.member6_cli: full application or saved State writing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .agents.writer import create_writer_node
from .member6 import stream_research
from .report_export import markdown_bytes, pdf_bytes


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("topic", nargs="?", default="多模态时间序列预测")
    p.add_argument("--mode", choices=["demo", "live"], default="demo")
    p.add_argument("--input", type=Path, help="只运行 Writer；输入 State 或 {state: ...}")
    p.add_argument("--compile-only", action="store_true", help="只汇编输入证据，不调用 Writer 模型")
    p.add_argument("--top-k", type=int, default=3)
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--output-dir", type=Path, default=Path("output/member6"))
    p.add_argument("--pdf", action="store_true")
    args = p.parse_args(argv)
    if args.compile_only and not args.input:
        p.error("--compile-only 需搭配 --input")
    try:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        if args.input:
            payload = json.loads(args.input.read_text("utf-8-sig"))
            state = payload.get("state", payload)
            state.update(create_writer_node(use_llm=not args.compile_only)(state))
        else:
            for event in stream_research(args.topic, mode=args.mode, top_k=args.top_k, max_critic_rounds=args.rounds):
                state = event["state"]
                print(f"完成：{event['node']}（审核轮次 {state.get('critic_round', 0)}）")
        report = state["final_report"]
        (args.output_dir/"report.md").write_bytes(markdown_bytes(report))
        (args.output_dir/"state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
        if args.pdf:
            (args.output_dir/"report.pdf").write_bytes(pdf_bytes(report))
        print(f"已保存至：{args.output_dir.resolve()}")
        return 0
    except Exception as exc:
        # Provider exception bodies may contain credentials or private source text.
        print(f"运行失败（{type(exc).__name__}）；请检查输入、输出目录及本地模型配置。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
