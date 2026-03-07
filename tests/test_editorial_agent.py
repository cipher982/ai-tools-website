import json
from types import SimpleNamespace

import pytest

from ai_tools_website.v1.editorial_agent import EDITORIAL_REVIEW_SYSTEM_PROMPT
from ai_tools_website.v1.editorial_agent import EditorialReview
from ai_tools_website.v1.editorial_agent import apply_editorial_review
from ai_tools_website.v1.editorial_agent import build_editorial_review_context
from ai_tools_website.v1.editorial_agent import build_editorial_review_user_prompt
from ai_tools_website.v1.editorial_agent import request_editorial_review
from ai_tools_website.v1.editorial_agent import resolve_editorial_review_model
from ai_tools_website.v1.editorial_agent import review_tool


class _FakeResponses:
    def __init__(self, output_text: str):
        self.output_text = output_text
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(output_text=self.output_text)


class _FakeClient:
    def __init__(self, output_text: str):
        self.responses = _FakeResponses(output_text)


@pytest.fixture
def sample_tool():
    return {
        "name": "OpenCode",
        "slug": "opencode",
        "category": "Code Assistants",
        "description": "Open-source, multi-model AI coding agent CLI/GUI.",
        "url": "https://github.com/opencode-ai/opencode",
        "pricing": None,
    }


def test_build_editorial_review_context_keeps_high_value_fields(sample_tool):
    context = build_editorial_review_context(sample_tool)
    assert context == {
        "name": "OpenCode",
        "slug": "opencode",
        "category": "Code Assistants",
        "description": "Open-source, multi-model AI coding agent CLI/GUI.",
        "url": "https://github.com/opencode-ai/opencode",
    }


def test_build_editorial_review_user_prompt_includes_tool_context(sample_tool):
    prompt = build_editorial_review_user_prompt(sample_tool)
    assert "Review this tool" in prompt
    assert "OpenCode" in prompt
    assert "Code Assistants" in prompt
    assert "opencode" in prompt


def test_resolve_editorial_review_model_prefers_specific_env(monkeypatch):
    monkeypatch.setenv("EDITORIAL_REVIEW_MODEL", "glm-editorial")
    monkeypatch.setenv("CONTENT_ENHANCER_MODEL", "glm-content")
    assert resolve_editorial_review_model() == "glm-editorial"


def test_resolve_editorial_review_model_falls_back_to_content_enhancer(monkeypatch):
    monkeypatch.delenv("EDITORIAL_REVIEW_MODEL", raising=False)
    monkeypatch.setenv("CONTENT_ENHANCER_MODEL", "glm-content")
    assert resolve_editorial_review_model() == "glm-content"


def test_editorial_review_schema_matches_openai_strict_requirements():
    schema = EditorialReview.model_json_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "action",
        "why",
        "ideal_user",
        "not_for",
        "decision_value",
        "page_angle",
        "suggested_sections",
        "comparison_candidates",
        "confidence",
    ]


def test_request_editorial_review_uses_structured_outputs(sample_tool):
    payload = {
        "action": "keep",
        "why": "Legitimate open-source coding agent with clear builder value.",
        "ideal_user": "Developers who want a self-hostable coding assistant.",
        "not_for": "Non-technical users who want a fully managed product.",
        "decision_value": ["Open source", "Multi-model support"],
        "page_angle": "The open-source coding agent for developers who want control.",
        "suggested_sections": ["Why choose it", "Alternatives"],
        "comparison_candidates": ["Aider", "Claude Code"],
        "confidence": 0.84,
    }
    client = _FakeClient(json.dumps(payload))

    review = request_editorial_review(client, sample_tool, model="glm-5", use_web_search=True)

    assert isinstance(review, EditorialReview)
    assert review.action == "keep"
    assert client.responses.last_kwargs["model"] == "glm-5"
    assert client.responses.last_kwargs["instructions"] == EDITORIAL_REVIEW_SYSTEM_PROMPT
    assert client.responses.last_kwargs["tools"] == [{"type": "web_search"}]
    assert client.responses.last_kwargs["text"]["format"]["type"] == "json_schema"


def test_request_editorial_review_can_skip_web_search(sample_tool):
    payload = {
        "action": "delete",
        "why": "Cheat tool.",
        "ideal_user": None,
        "not_for": "Everyone.",
        "decision_value": [],
        "page_angle": None,
        "suggested_sections": [],
        "comparison_candidates": [],
        "confidence": 1.0,
    }
    client = _FakeClient(json.dumps(payload))

    review = request_editorial_review(client, sample_tool, model="glm-5", use_web_search=False)

    assert review.action == "delete"
    assert "tools" not in client.responses.last_kwargs


def test_request_editorial_review_raises_on_invalid_json(sample_tool):
    client = _FakeClient("not-json")
    with pytest.raises(RuntimeError, match="invalid JSON"):
        request_editorial_review(client, sample_tool, model="glm-5")


def test_review_tool_uses_openai_base_url_when_present(sample_tool, monkeypatch):
    captured = {}

    class DummyOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

    expected = EditorialReview(
        action="keep",
        why="Legitimate tool.",
        ideal_user="Builders",
        not_for=None,
        decision_value=[],
        page_angle=None,
        suggested_sections=[],
        comparison_candidates=[],
        confidence=0.7,
    )

    def fake_request(client, tool, *, model, use_web_search):
        captured["client"] = client
        captured["model"] = model
        captured["use_web_search"] = use_web_search
        return expected

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.drose.io")
    monkeypatch.setattr("openai.OpenAI", DummyOpenAI)
    monkeypatch.setattr("ai_tools_website.v1.editorial_agent.request_editorial_review", fake_request)

    review = review_tool(sample_tool, model="glm-5", use_web_search=False)

    assert review == expected
    assert captured["client_kwargs"] == {
        "api_key": "test-key",
        "base_url": "https://llm.drose.io",
    }
    assert captured["model"] == "glm-5"
    assert captured["use_web_search"] is False


def test_review_tool_skips_base_url_when_unset(sample_tool, monkeypatch):
    captured = {}

    class DummyOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

    expected = EditorialReview(
        action="keep",
        why="Legitimate tool.",
        ideal_user="Builders",
        not_for=None,
        decision_value=[],
        page_angle=None,
        suggested_sections=[],
        comparison_candidates=[],
        confidence=0.7,
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setattr("openai.OpenAI", DummyOpenAI)
    monkeypatch.setattr(
        "ai_tools_website.v1.editorial_agent.request_editorial_review",
        lambda client, tool, **kwargs: expected,
    )

    review = review_tool(sample_tool, model="glm-5")

    assert review == expected
    assert captured["client_kwargs"] == {"api_key": "test-key"}


def test_apply_editorial_review_merges_nested_and_root_fields(sample_tool):
    review = EditorialReview(
        action="noindex",
        why="Useful but too niche for promotion.",
        ideal_user="Advanced tinkerers.",
        not_for="Most mainstream users.",
        decision_value=["Strong niche workflow"],
        page_angle="A niche but capable option for advanced users.",
        suggested_sections=["Who it's for", "Why skip it"],
        comparison_candidates=["Aider"],
        confidence=0.73,
    )

    updated = apply_editorial_review(sample_tool, review, reviewed_at="2026-03-07T12:00:00+00:00", model="glm-5")

    assert updated["action"] == "noindex"
    assert updated["last_reviewed_at"] == "2026-03-07T12:00:00+00:00"
    assert updated["editorial"]["action"] == "noindex"
    assert updated["editorial"]["why"] == "Useful but too niche for promotion."
    assert updated["editorial"]["confidence"] == 0.73
    assert updated["editorial"]["model"] == "glm-5"
