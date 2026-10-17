"""Replay saved, hash-checked API bytes through the actual Search implementation.

This is an offline replay of an earlier retrieval, not a new database search.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from examples.search_demo import _save
from research_assistant.agents.search import create_search_node
from research_assistant.search.config import SearchConfig
from research_assistant.search.crossref import CrossrefProvider
from research_assistant.search.openalex import OpenAlexProvider
from research_assistant.search.models import ProviderError
from research_assistant.search.providers import ArxivProvider, SemanticScholarProvider
from research_assistant.search.transport import HttpResponse


class RecordedTransport:
    """Exact request matching; an uncaptured request always fails offline."""

    def __init__(self, audit: dict, raw_dir: Path):
        self.recordings = {}
        for request in audit["requests"]:
            evidence = request.get("response_evidence") or {}
            if request["status"] == "success" and evidence:
                self.recordings[evidence["request_url"]] = evidence
        self.raw_dir = raw_dir

    def get(self, url: str, headers=None) -> HttpResponse:
        evidence = self.recordings.get(url)
        if evidence is None:
            raise ProviderError("该请求在历史录制中未成功；离线重放不会联网补充")
        digest = evidence["response_sha256"]
        # Never trust arbitrary paths from an input JSON when finding raw data.
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ProviderError("录制中的响应哈希格式无效")
        try:
            body = (self.raw_dir / (digest + ".response")).read_bytes()
        except OSError:
            raise ProviderError("录制缺少对应的原始响应文件") from None
        if hashlib.sha256(body).hexdigest() != digest:
            raise ProviderError("原始响应 SHA-256 不匹配，拒绝重放")
        return HttpResponse(body, url, evidence["retrieved_at"], digest)


def replay(path: Path, raw_dir: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    audit = payload["search_audit"]
    if audit["counts"]["existing_input"] != 0:
        raise ValueError("独立重放示例需要首轮录制；跨轮状态请使用真实 Search --input")
    config = SearchConfig(**{**audit["config"], "use_llm": False})
    transport = RecordedTransport(audit, raw_dir)
    constructors = {"openalex": OpenAlexProvider, "arxiv": ArxivProvider, "semantic_scholar": SemanticScholarProvider, "crossref": CrossrefProvider}
    providers = [constructors[source](transport=transport, **({"api_key": ""} if source == "semantic_scholar" else {})) for source in config.sources]
    state = {key: value for key, value in payload["state"].items() if key not in {"papers", "errors"}}
    # Use the recorded query plan exactly, without regenerating a past LLM call.
    state["search_keywords"] = audit["queries"]
    state.pop("critic_result", None)
    agent = create_search_node(config=config, providers=providers)
    delta = agent(state)
    expected = payload["state"]["papers"]
    if delta["papers"] != expected:
        raise ValueError("重放结果与录制结果不同，请检查录制版本和当前筛选实现")
    return {"notice": "离线重放：使用历史真实 API 原文并验证 SHA-256；没有发起新检索或模型调用。",
            "recorded_started_at": audit["started_at"], "verified_equal": True,
            "state": {**state, **delta}, "search_audit": agent.last_audit}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(__file__).parent / "fixtures" / "search_recording_openalex"
    parser.add_argument("--input", type=Path, default=default / "search_round1.json")
    parser.add_argument("--raw-dir", type=Path, default=default / "raw")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        _save(replay(args.input, args.raw_dir), args.output)
    except (OSError, ValueError, KeyError, ProviderError) as exc:
        parser.exit(2, str(exc) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
