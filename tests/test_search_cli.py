"""CLI tests are offline and must not consume API or model calls."""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from examples.search_demo import main
from research_assistant.search.config import SearchConfig


@pytest.mark.parametrize("source_args,expected", [
    ([], ("openalex",)),
    (["--source", "openalex"], ("openalex",)),
    (["--source", "arxiv"], ("arxiv",)),
    (["--source", "arxiv", "--source", "semantic_scholar", "--source", "crossref"],
     ("arxiv", "semantic_scholar", "crossref")),
    (["--source", "crossref"], ("crossref",)),
])
def test_source_default_and_explicit_selection_reach_node_without_network(monkeypatch, tmp_path, source_args, expected):
    node = Mock(return_value={"papers": []})
    node.last_audit = {"status": "success", "counts": {
        "api_records": 0, "api_hits": 0, "new_selected": 0, "returned": 0,
    }}
    factory = Mock(return_value=node)
    monkeypatch.setattr("examples.search_demo.create_search_node", factory)
    output = tmp_path / "result.json"
    assert main(["time series", *source_args, "--output", str(output)]) == 0
    assert SearchConfig().sources == ("openalex",)
    assert factory.call_args.kwargs["config"].sources == expected
    node.assert_called_once()


def test_plan_only_never_constructs_live_node_or_model(monkeypatch, tmp_path):
    factory = Mock(side_effect=AssertionError("No API in planning"))
    monkeypatch.setattr("examples.search_demo.create_search_node", factory)
    output = tmp_path / "plan.json"
    assert main(["多模态时间序列预测", "--question", "时间序列如何融合文本？", "--plan-only", "--use-llm", "--output", str(output)]) == 0
    payload = json.loads(output.read_text("utf-8"))
    assert any("text" in query for query in payload["queries"])
    assert "未取得任何论文" in payload["notice"]
    factory.assert_not_called()


@pytest.mark.parametrize("input_value", [[], {"state": []}, {"topic": ""}])
def test_invalid_input_is_reported_without_network(tmp_path, input_value):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(input_value), encoding="utf-8")
    output = tmp_path / "result.json"
    assert main(["--input", str(source), "--plan-only", "--output", str(output)]) == 2
    assert "error" in json.loads(output.read_text("utf-8"))


def test_unwritable_output_returns_failure_instead_of_uncaught_error(tmp_path):
    obstruction = tmp_path / "file"
    obstruction.write_text("MOCK_ONLY", encoding="utf-8")
    assert main(["test", "--plan-only", "--output", str(obstruction / "result.json")]) == 2
