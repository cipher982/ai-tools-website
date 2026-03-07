"""Bounded editorial review contract for v2 tool triage and refresh flows."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from ai_tools_website.v1.openai_utils import extract_responses_api_text
from ai_tools_website.v1.openai_utils import parse_json_response

EditorialAction = Literal["keep", "noindex", "delete", "needs_review"]


class EditorialReview(BaseModel):
    """Structured editorial decision for a tool page."""

    model_config = ConfigDict(extra="forbid")

    action: EditorialAction
    why: str
    ideal_user: str | None = None
    not_for: str | None = None
    decision_value: list[str] = Field(default_factory=list)
    page_angle: str | None = None
    suggested_sections: list[str] = Field(default_factory=list)
    comparison_candidates: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


EDITORIAL_REVIEW_SYSTEM_PROMPT = """You are the editorial agent for a useful modern AI tools website.
Your goal is NOT to maximize page count.
Your goal is to help a visitor decide quickly whether a tool is worth their time.

You may choose one action:
- keep: deserves a tool page and public listing
- noindex: page can exist but should not be indexed or promoted
- delete: low-value, harmful, junk, or off-strategy for this site
- needs_review: ambiguous and needs human review

Editorial rules:
- Be opinionated and specific.
- Delete obvious cheat, exploit, spam, scam, or gambling-adjacent tools.
- Prefer legitimate builder, creator, and practical workflow tools.
- If a page cannot add real decision value, do not force it into keep.
- Do not invent facts.

Return strict JSON matching the provided schema.
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_editorial_review_model() -> str:
    """Resolve the model used for editorial review lazily at runtime."""
    model = os.getenv("EDITORIAL_REVIEW_MODEL") or os.getenv("CONTENT_ENHANCER_MODEL")
    if not model:
        raise RuntimeError("Set EDITORIAL_REVIEW_MODEL or CONTENT_ENHANCER_MODEL before requesting editorial review.")
    return model


def build_editorial_review_context(tool: dict[str, Any]) -> dict[str, Any]:
    """Trim a tool record down to the fields worth sending to the reviewer."""
    context = {
        "name": tool.get("name"),
        "slug": tool.get("slug"),
        "category": tool.get("category"),
        "description": tool.get("description"),
        "url": tool.get("url"),
        "pricing": tool.get("pricing"),
        "tags": tool.get("tags"),
        "action": tool.get("action"),
        "editorial": tool.get("editorial"),
        "enhanced_content_v2": tool.get("enhanced_content_v2"),
    }
    return {key: value for key, value in context.items() if value not in (None, [], {}, "")}


def build_editorial_review_user_prompt(tool: dict[str, Any]) -> str:
    """Build the user prompt for an editorial review request."""
    context = build_editorial_review_context(tool)
    return (
        "Review this tool for a useful, trustworthy AI tools website. "
        "Focus on whether the page should exist and what decision value it can offer.\n\n"
        f"Tool:\n{json.dumps(context, indent=2)}\n"
    )


def request_editorial_review(
    client: Any,
    tool: dict[str, Any],
    *,
    model: str | None = None,
    use_web_search: bool = True,
) -> EditorialReview:
    """Request a structured editorial review from the Responses API."""
    resolved_model = model or resolve_editorial_review_model()
    request_kwargs: dict[str, Any] = {
        "model": resolved_model,
        "instructions": EDITORIAL_REVIEW_SYSTEM_PROMPT,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": build_editorial_review_user_prompt(tool)}],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "editorial_review",
                "strict": True,
                "schema": EditorialReview.model_json_schema(),
            }
        },
    }
    if use_web_search:
        request_kwargs["tools"] = [{"type": "web_search"}]

    response = client.responses.create(**request_kwargs)
    output_text = extract_responses_api_text(response)
    if not output_text:
        raise RuntimeError("Editorial review returned no text output.")

    parsed = parse_json_response(output_text, context=f"editorial review for {tool.get('name', 'tool')}")
    if not parsed:
        raise RuntimeError("Editorial review returned invalid JSON.")

    return EditorialReview.model_validate(parsed)


def review_tool(
    tool: dict[str, Any],
    *,
    client: Any | None = None,
    model: str | None = None,
    use_web_search: bool = True,
) -> EditorialReview:
    """Convenience wrapper that creates an OpenAI client lazily when needed."""
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return request_editorial_review(client, tool, model=model, use_web_search=use_web_search)


def apply_editorial_review(
    tool: dict[str, Any],
    review: EditorialReview,
    *,
    reviewed_at: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Merge a structured review back into the canonical tool record."""
    merged = deepcopy(tool)
    reviewed_at = reviewed_at or _now_iso()
    editorial = deepcopy(merged.get("editorial") or {})
    editorial.update(
        {
            "action": review.action,
            "why": review.why,
            "ideal_user": review.ideal_user,
            "not_for": review.not_for,
            "decision_value": review.decision_value,
            "page_angle": review.page_angle,
            "suggested_sections": review.suggested_sections,
            "comparison_candidates": review.comparison_candidates,
            "confidence": review.confidence,
            "reviewed_at": reviewed_at,
        }
    )
    if model:
        editorial["model"] = model

    merged["action"] = review.action
    merged["editorial"] = editorial
    merged["last_reviewed_at"] = reviewed_at
    return merged
