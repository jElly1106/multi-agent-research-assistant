"""Member 2 command line entry. No demo papers are used by this program."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

from research_assistant.agents.search import SearchUnavailableError, create_search_node
from research_assistant.search.config import SearchConfig
from research_assistant.search.keywords import generate_queries


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="真实科研文献检索；关键词规划不等于实际搜得论文")
    p.add_argument("topic", nargs="?", help="研究主题；未给出时从 --input 读取")
    p.add_argument("--input", type=Path, help="已有 State JSON 或 {state: ...}；支持 Critic 补搜")
    p.add_argument("--question", action="append", default=[], help="研究问题，可重复")
    p.add_argument("--query", action="append", default=[], help="Coordinator 检索短语，可重复")
    p.add_argument("--followup", action="append", default=[], help="Critic 补搜短语，可重复，优先执行")
    p.add_argument("--source", choices=["openalex", "arxiv", "semantic_scholar", "crossref"], action="append")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--max-queries", type=int, default=6)
    p.add_argument("--results-per-query", type=int, default=20)
    p.add_argument("--year-from", type=int)
    p.add_argument("--year-to", type=int)
    p.add_argument("--required-keyword", action="append", default=[])
    p.add_argument("--exclude-keyword", action="append", default=[])
    p.add_argument("--keyword-match", choices=["any", "all"], default="any")
    p.add_argument("--min-relevance", type=float, default=0.12)
    p.add_argument("--timeout", type=float, default=20)
    p.add_argument("--max-retries", type=int, default=2)
    p.add_argument("--arxiv-proxy-mode", choices=["auto", "direct", "system"], default=os.getenv("ARXIV_PROXY_MODE", "auto"), help="arXiv 路由：auto 优先直连，网络失败时在重试预算内切换系统代理；不会修改系统代理")
    p.add_argument("--use-llm", action="store_true", help="显式启用已配置模型生成查询；失败时规则回退")
    p.add_argument("--plan-only", action="store_true", help="仅规则生成查询，不联网、不调用模型")
    p.add_argument("--output", type=Path)
    p.add_argument("--audit-dir", type=Path, help="保留逐轮审计与真实 API 原始响应")
    return p


def _save(payload: dict, path: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    if path is None:
        print(text)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text + "\n", encoding="utf-8")
        temporary.replace(path)
        label = "失败记录已保存" if "error" in payload else "结果已保存"
        print(f"{label}：{path.resolve()}")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = parser()
    args = p.parse_args(argv)
    agent = None
    try:
        state = {}
        if args.input:
            payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("--input 必须是 State JSON 对象")
            state = payload.get("state", payload)
            if not isinstance(state, dict):
                raise ValueError("--input 的 state 必须是对象")
        if args.topic:
            state["topic"] = args.topic
        state.setdefault("topic", "Multimodal Time Series Forecasting")
        if args.question:
            state["research_questions"] = args.question
        if args.query:
            state["search_keywords"] = args.query
        if args.followup:
            state["critic_result"] = {"decision": "FAIL", "new_search_queries": args.followup}
        config = SearchConfig(top_k=args.top_k, max_queries=args.max_queries, results_per_query=args.results_per_query,
            year_from=args.year_from, year_to=args.year_to, required_keywords=tuple(args.required_keyword),
            excluded_keywords=tuple(args.exclude_keyword), keyword_match=args.keyword_match,
            min_relevance=args.min_relevance, sources=tuple(args.source or SearchConfig().sources),
            timeout=args.timeout, max_retries=args.max_retries, use_llm=args.use_llm, arxiv_proxy_mode=args.arxiv_proxy_mode)
        if args.plan_only:
            queries, warnings = generate_queries(state, max_queries=config.max_queries)
            _save({"notice": "仅规划查询；未请求数据库或模型，未取得任何论文。", "queries": queries, "warnings": warnings}, args.output)
            return 0
        agent = create_search_node(config=config, audit_dir=args.audit_dir)
        result = agent(state)
        _save({"notice": "论文元数据来自数据库 API；相关性分数是本地关键词覆盖分，不是论文质量或真实性概率。恢复的已有 State 需保留上轮来源证据。",
               "state": {**state, **result}, "search_audit": agent.last_audit}, args.output)
        counts = agent.last_audit["counts"]
        print(f"状态 {agent.last_audit['status']}；API原始 {counts['api_records']} 条，解析 {counts['api_hits']} 条，本轮新增 {counts['new_selected']} 篇，返回完整列表 {counts['returned']} 篇。", file=sys.stderr)
        return 0
    except (SearchUnavailableError, ValueError, OSError) as exc:
        # All user input errors are local; API errors have already been sanitized.
        failure = {"notice": "检索失败；没有使用示例论文替代真实结果。", "error": str(exc)}
        if agent is not None:
            failure["search_audit"] = agent.last_audit
        if args.output:
            try:
                _save(failure, args.output)
            except OSError:
                print("无法写入指定输出文件，请检查目录权限或磁盘空间。", file=sys.stderr)
        print(failure["error"], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
