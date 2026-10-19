"""Synthetic model configuration tests; never contact a provider."""
import builtins
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError

from research_assistant.agents.reader import LLMAbstractAnalyzer, LLMUnavailableError, RecoverableAnalysisError
from research_assistant.schemas import Paper, PaperAnalysis


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("LLM_MODEL", "synthetic-model")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API", raising=False)
    monkeypatch.delenv("READER_ENABLE_THINKING", raising=False)


@pytest.mark.parametrize("api", [None, "chat_completions", "responses"])
def test_client_configuration(api, monkeypatch):
    if api:
        monkeypatch.setenv("LLM_API", api)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://synthetic.invalid/v1/")
    constructor = Mock()
    monkeypatch.setattr("langchain_openai.ChatOpenAI", constructor)
    LLMAbstractAnalyzer()
    kwargs = constructor.call_args.kwargs
    assert kwargs["base_url"] == "https://synthetic.invalid/v1"
    assert kwargs["use_responses_api"] == (api == "responses")
    assert kwargs["timeout"] == 120 and kwargs["max_retries"] == 2
    assert "temperature" not in kwargs
    assert "extra_body" not in kwargs
    assert (kwargs.get("store") is False) == (api == "responses")
    constructor.return_value.with_structured_output.assert_called_once_with(
        PaperAnalysis, method="json_schema", strict=True
    )


@pytest.mark.parametrize("name,value", [
    ("LLM_API", "invalid"), ("OPENAI_BASE_URL", "ftp://host/v1"),
    ("OPENAI_BASE_URL", "https://host/v1/responses/"),
    ("OPENAI_BASE_URL", "https://host/v1/chat/completions"),
    ("OPENAI_BASE_URL", "https:///missing-host"),
])
def test_invalid_config_is_explicit(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        LLMAbstractAnalyzer()


def test_missing_client_dependency(monkeypatch):
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name == "langchain_openai":
            raise ImportError("synthetic missing dependency")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", importing)
    with pytest.raises(LLMUnavailableError):
        LLMAbstractAnalyzer()


def test_provider_failure_is_recoverable():
    analyzer = object.__new__(LLMAbstractAnalyzer)
    analyzer._structured_llm = Mock()
    analyzer._structured_llm.invoke.side_effect = APIConnectionError(request=httpx.Request("POST", "https://synthetic.invalid"))
    paper = Paper(title="Synthetic", authors=[], source="synthetic", abstract="Synthetic evidence")
    with pytest.raises(RecoverableAnalysisError):
        analyzer.analyze(paper)
    analyzer._structured_llm.invoke.side_effect = AttributeError("synthetic bug")
    with pytest.raises(AttributeError):
        analyzer.analyze(paper)


@pytest.mark.parametrize("enabled", ["0", "1"])
def test_explicit_provider_thinking_switch(enabled, monkeypatch):
    monkeypatch.setenv("READER_ENABLE_THINKING", enabled)
    constructor = Mock()
    monkeypatch.setattr("langchain_openai.ChatOpenAI", constructor)
    LLMAbstractAnalyzer(max_output_tokens=8192, max_retries=0)
    assert constructor.call_args.kwargs["extra_body"] == {"enable_thinking": enabled == "1"}
    assert constructor.call_args.kwargs["max_tokens"] == 8192
    assert constructor.call_args.kwargs["max_retries"] == 0


@pytest.mark.parametrize("flag,api", [("false", "chat_completions"), ("", "chat_completions"),
                                      ("0", "responses")])
def test_bad_thinking_setting_prevents_client_creation(flag, api, monkeypatch):
    monkeypatch.setenv("READER_ENABLE_THINKING", flag)
    monkeypatch.setenv("LLM_API", api)
    constructor = Mock()
    monkeypatch.setattr("langchain_openai.ChatOpenAI", constructor)
    with pytest.raises(ValueError, match="READER_ENABLE_THINKING"):
        LLMAbstractAnalyzer()
    constructor.assert_not_called()
