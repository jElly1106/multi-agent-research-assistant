"""Synthetic papers and model responses only; never calls a provider."""
from copy import deepcopy
from io import BytesIO
from unittest.mock import Mock

import pytest

from research_assistant.agents.writer import create_writer_node


@pytest.fixture
def material():
    return {
        "topic": "合成研究主题", "research_scope": "仅合成材料",
        "research_questions": ["合成方法有什么局限？"],
        "papers": [{"title": "SYNTHETIC A", "authors": ["Synthetic Author"], "year": 2026,
                    "source": "synthetic", "url": "https://example.test/paper"}],
        "paper_analysis": [{"paper_title": "SYNTHETIC A", "problem": "合成问题", "motivation": "合成动机",
                            "method": "合成方法", "datasets": ["合成数据集"], "metrics": [],
                            "main_results": "", "contributions": [], "limitations": ["仅合成验证"]}],
        "method_summary": {"categories": [{"name": "合成分类", "description": "测试用", "papers": ["SYNTHETIC A"]}],
                           "comparison_table": [{"paper": "SYNTHETIC A", "input": "合成输入", "fusion": "拼接",
                                                 "backbone": "合成主干", "dataset": "不应采用的模型补造值"}],
                           "summary": "合成总结（依据：SYNTHETIC A）", "evolution": []},
        "critic_result": {"decision": "PASS"},
    }


@pytest.fixture
def response():
    return {"background": [{"text": "合成背景", "papers": ["SYNTHETIC A"]}],
            "answers": [{"question": "合成方法有什么局限？", "statements": [
                {"text": "方法仅进行合成验证", "papers": ["SYNTHETIC A"]}], "evidence_gap": "缺少真实实验"}],
            "directions": [{"text": "建议在真实数据上验证，仍属待验证假设", "papers": ["SYNTHETIC A"]}]}


def test_model_report_preserves_contract_and_sources(material, response):
    before = deepcopy(material)
    model = Mock()
    model.invoke.return_value = response
    result = create_writer_node(model)(material)
    assert set(result) == {"final_report"}
    report = result["final_report"]
    assert report["references"] == ["SYNTHETIC A"]
    assert all(f"## {i}." in report["markdown"] for i in range(1, 9))
    assert "合成数据集" in report["markdown"]
    assert "不应采用的模型补造值" not in report["markdown"]
    assert "演示材料" in report["markdown"]
    assert "前序材料审核通过" in report["markdown"]
    assert material == before
    assert len(model.invoke.call_args.args[0]) == 2


@pytest.mark.parametrize("section", ["background", "directions", "answers"])
def test_invented_citation_is_rejected(material, response, section):
    target = response[section][0]
    if section == "answers":
        target = target["statements"][0]
    target["papers"] = ["INVENTED PAPER"]
    with pytest.raises(ValueError, match="未知或无阅读证据"):
        create_writer_node(Mock(invoke=Mock(return_value=response)))(material)


@pytest.mark.parametrize("answers", [[], [{"question": "被改写的问题", "statements": [], "evidence_gap": "不足"}]])
def test_question_coverage_is_enforced(material, response, answers):
    response["answers"] = answers
    with pytest.raises(ValueError, match="完整回答"):
        create_writer_node(Mock(invoke=Mock(return_value=response)))(material)


def test_abstention_requires_explicit_gap(material, response):
    response["answers"][0].update(statements=[], evidence_gap="")
    with pytest.raises(ValueError, match="证据缺口"):
        create_writer_node(Mock(invoke=Mock(return_value=response)))(material)


def test_unread_paper_cannot_support_model_claim(material, response):
    material["papers"].append({"title": "UNREAD", "authors": [], "source": "synthetic"})
    response["background"][0]["papers"] = ["UNREAD"]
    with pytest.raises(ValueError, match="无阅读证据"):
        create_writer_node(Mock(invoke=Mock(return_value=response)))(material)


def test_failure_and_missing_configuration_are_not_disguised(material, monkeypatch):
    model = Mock(invoke=Mock(side_effect=TimeoutError("synthetic timeout")))
    with pytest.raises(TimeoutError):
        create_writer_node(model)(material)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="Writer"):
        create_writer_node()(material)


@pytest.mark.parametrize("critic", [None, {"decision": "FAIL", "feedback": ["合成遗留问题"], "new_search_queries": ["合成补搜"]}])
def test_unresolved_review_is_kept(material, critic):
    material["critic_result"] = critic
    material["termination_reason"] = "max_critic_rounds"
    report = create_writer_node(use_llm=False)(material)["final_report"]
    assert "审核未完全通过" in report["markdown"]
    if critic:
        assert "合成遗留问题" in report["markdown"] and "合成补搜" in report["markdown"]


def test_empty_evidence_never_calls_model():
    model = Mock()
    result = create_writer_node(model)({"topic": "空材料", "papers": [], "paper_analysis": []})
    model.invoke.assert_not_called()
    assert result["final_report"]["references"] == []
    assert "证据不足" in result["final_report"]["markdown"]


@pytest.mark.parametrize("case", ["title", "duplicate", "analysis", "category", "comparison"])
def test_invalid_source_associations_rejected_before_model(material, case):
    if case == "title":
        material["papers"][0]["title"] = " "
    elif case == "duplicate":
        material["papers"].append({**material["papers"][0], "year": 2025})
    elif case == "analysis":
        material["paper_analysis"][0]["paper_title"] = "UNKNOWN"
    elif case == "category":
        material["method_summary"]["categories"][0]["papers"] = ["UNKNOWN"]
    else:
        material["method_summary"]["comparison_table"][0]["paper"] = "UNKNOWN"
    model = Mock()
    with pytest.raises(ValueError):
        create_writer_node(model)(material)
    model.invoke.assert_not_called()


def test_untrusted_text_and_urls_are_not_active_markup(material):
    material["paper_analysis"][0]["method"] = "<script>bad()</script> [click](javascript:evil)"
    material["papers"][0]["url"] = "javascript:evil"
    report = create_writer_node(use_llm=False)(material)
    text = report["final_report"]["markdown"]
    assert "<script>" not in text
    assert "[click](javascript:evil)" not in text
    assert "来源链接未提供" in text


def test_new_run_replaces_previous_references(material):
    node = create_writer_node(use_llm=False)
    first = node(material)
    second = node({"topic": "新一轮", "papers": [], "paper_analysis": [], **first})
    assert second["final_report"]["references"] == []
    assert "SYNTHETIC A" not in second["final_report"]["markdown"]


def test_pdf_preserves_chinese_warning_and_pagination(material):
    pytest.importorskip("reportlab")
    from pypdf import PdfReader
    from research_assistant.report_export import markdown_bytes, pdf_bytes
    material["critic_result"]["decision"] = "FAIL"
    material["paper_analysis"][0]["limitations"] = ["合成局限与长文本验证" * 20] * 18
    report = create_writer_node(use_llm=False)(material)["final_report"]
    assert markdown_bytes(report).decode("utf-8") == report["markdown"]
    pdf = pdf_bytes(report)
    parsed = PdfReader(BytesIO(pdf))
    assert len(parsed.pages) >= 2
    content = "".join(p.extract_text() for p in parsed.pages)
    assert "审核未完全通过" in content and "SYNTHETIC A" in content
