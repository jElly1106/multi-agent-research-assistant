import json
from unittest.mock import Mock

import httpx
import pytest
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from research_assistant.llm import create_structured_model


class ProbeOutput(BaseModel):
    answer: str


@pytest.fixture(autouse=True)
def model_config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("LLM_MODEL", "mock-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://mock.invalid/v1")
    monkeypatch.setenv("LLM_API", "responses")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


@pytest.mark.parametrize("api", ["responses", "chat_completions"])
def test_sdk_posts_to_correct_endpoint_and_parses_structured_json(api, monkeypatch):
    monkeypatch.setenv("LLM_API", api)
    requests = []

    def handler(request):
        requests.append(request)
        content = json.dumps({"answer": "ok"})
        if api == "responses":
            data = {
                "id": "resp_mock", "object": "response", "created_at": 1,
                "status": "completed", "model": "mock-model",
                "output": [{"id": "msg_mock", "type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": content, "annotations": []}]}],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            }
        else:
            data = {
                "id": "chatcmpl_mock", "object": "chat.completion", "created": 1, "model": "mock-model",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        return httpx.Response(200, json=data)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr("langchain_openai.ChatOpenAI", lambda **kwargs: ChatOpenAI(http_client=client, **kwargs))
        result = create_structured_model(ProbeOutput, label="test").invoke([("human", "Return ok")])
    assert result.answer == "ok"
    assert len(requests) == 1
    request = requests[0]
    assert request.headers["authorization"] == "Bearer mock-key"
    body = json.loads(request.content)
    assert body["model"] == "mock-model"
    assert "temperature" not in body
    if api == "responses":
        assert request.url.path == "/v1/responses"
        assert body["store"] is False
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["text"]["format"]["strict"] is True
    else:
        assert request.url.path == "/v1/chat/completions"
        assert body["response_format"]["type"] == "json_schema"


@pytest.mark.parametrize("suffix", ["/responses", "/responses/", "/chat/completions"])
def test_full_request_url_is_rejected(suffix, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://mock.invalid/v1" + suffix)
    with pytest.raises(ValueError, match="API 根地址"):
        create_structured_model(ProbeOutput, label="test")


def test_unknown_api_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_API", "typo")
    with pytest.raises(ValueError, match="LLM_API"):
        create_structured_model(ProbeOutput, label="test")


def test_default_configuration_keeps_chat_completions(monkeypatch):
    monkeypatch.delenv("LLM_API")
    constructor = Mock()
    monkeypatch.setattr("langchain_openai.ChatOpenAI", constructor)
    create_structured_model(ProbeOutput, label="test")
    assert constructor.call_args.kwargs["use_responses_api"] is False


def test_coordinator_uses_shared_responses_configuration(monkeypatch):
    from research_assistant.agents.coordinator import coordinator_node
    from research_assistant.schemas import CoordinatorOutput

    monkeypatch.setenv("COORDINATOR_USE_LLM", "1")
    constructor = Mock()
    constructor.return_value.with_structured_output.return_value.invoke.return_value = CoordinatorOutput(
        research_scope="mock", research_questions=["mock"], search_directions=["mock"],
        search_keywords=["mock"], research_plan=["mock"],
    )
    monkeypatch.setattr("langchain_openai.ChatOpenAI", constructor)
    assert coordinator_node({"topic": "mock"})["research_scope"] == "mock"
    assert constructor.call_args.kwargs["use_responses_api"] is True
    constructor.return_value.with_structured_output.assert_called_once_with(
        CoordinatorOutput, method="json_schema", strict=True
    )
