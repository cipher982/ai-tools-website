"""Editorial visibility helpers for v2 action gating."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

EDITORIAL_ACTION_KEEP = "keep"
EDITORIAL_ACTION_NOINDEX = "noindex"
EDITORIAL_ACTION_DELETE = "delete"
EDITORIAL_ACTION_NEEDS_REVIEW = "needs_review"

VALID_EDITORIAL_ACTIONS = {
    EDITORIAL_ACTION_KEEP,
    EDITORIAL_ACTION_NOINDEX,
    EDITORIAL_ACTION_DELETE,
    EDITORIAL_ACTION_NEEDS_REVIEW,
}

TOOL_STATUS_PUBLISHED = "published"
TOOL_STATUS_HIDDEN = "hidden"
TOOL_STATUS_CANDIDATE = "candidate"
TOOL_STATUS_REJECTED = "rejected"

VALID_TOOL_STATUSES = {
    TOOL_STATUS_PUBLISHED,
    TOOL_STATUS_HIDDEN,
    TOOL_STATUS_CANDIDATE,
    TOOL_STATUS_REJECTED,
}

HIGH_RISK_KEYWORDS = {
    "aimmy",
    "aimbot",
    "cheat",
    "exploit",
    "hack",
    "bypass",
    "deepnude",
    "easydeepnude",
    "uncensored",
    "nsfw",
    "undressai",
    "undresser",
}

GAMBLING_CONTEXT_KEYWORDS = {
    "aviator",
    "betting",
    "casino",
    "slot",
    "gambling",
}

RISKY_PHRASES = {
    "aim alignment",
    "aim assist",
    "anti-ban",
    "auto-trigger",
    "script executor",
    "unlocked edition",
    "undressed versions",
    "undressing tool",
}


def get_editorial_action(tool: Mapping[str, Any] | None) -> str:
    """Return the normalized editorial action for a tool.

    Missing or invalid values default to `keep` so legacy records remain public.
    Supports both root-level `action` and nested `editorial.action` during the
    transition to the v2 schema.
    """
    if not isinstance(tool, Mapping):
        return EDITORIAL_ACTION_KEEP

    action = None
    editorial = tool.get("editorial")
    if isinstance(editorial, Mapping):
        action = editorial.get("action")

    if action is None:
        action = tool.get("action")

    if not isinstance(action, str):
        return EDITORIAL_ACTION_KEEP

    normalized = action.strip().lower()
    if normalized in VALID_EDITORIAL_ACTIONS:
        return normalized
    return EDITORIAL_ACTION_KEEP


def _get_tool_tokens(tool: Mapping[str, Any]) -> set[str]:
    haystacks = [
        str(tool.get("name") or "").lower(),
        str(tool.get("description") or "").lower(),
        str(tool.get("url") or "").lower(),
        str(tool.get("category") or "").lower(),
        " ".join(str(tag).lower() for tag in tool.get("tags") or []),
    ]
    return set(re.findall(r"[a-z0-9]+", " ".join(haystacks)))


def get_policy_flags(tool: Mapping[str, Any] | None) -> list[str]:
    """Return hard-deny policy flags for obviously off-strategy or junk tools."""
    if not isinstance(tool, Mapping):
        return []

    tokens = _get_tool_tokens(tool)
    text = " ".join(
        [
            str(tool.get("name") or "").lower(),
            str(tool.get("description") or "").lower(),
            str(tool.get("url") or "").lower(),
            " ".join(str(tag).lower() for tag in tool.get("tags") or []),
        ]
    )

    flags = sorted(keyword for keyword in HIGH_RISK_KEYWORDS if keyword in tokens)
    flags.extend(sorted(keyword for keyword in GAMBLING_CONTEXT_KEYWORDS if keyword in tokens))
    flags.extend(sorted(phrase for phrase in RISKY_PHRASES if phrase in text))

    deduped: list[str] = []
    seen: set[str] = set()
    for flag in flags:
        if flag in seen:
            continue
        seen.add(flag)
        deduped.append(flag)
    return deduped


def _get_explicit_status(tool: Mapping[str, Any] | None) -> str | None:
    if not isinstance(tool, Mapping):
        return None

    value = tool.get("status")
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower()
    if normalized in VALID_TOOL_STATUSES:
        return normalized
    return None


def _has_legacy_noindex_flag(tool: Mapping[str, Any] | None) -> bool:
    if not isinstance(tool, Mapping):
        return False

    enhanced_v2 = tool.get("enhanced_content_v2")
    tier = None
    if isinstance(enhanced_v2, Mapping):
        tier = enhanced_v2.get("tier")
    if tier is None:
        tier = tool.get("_tier")
    if tier == "noindex":
        return True

    return tool.get("noindex") is True


def get_tool_status(tool: Mapping[str, Any] | None) -> str:
    """Return the effective public status for a tool record.

    Explicit status is the forward-looking source of truth. Legacy editorial
    actions remain supported during the migration. Hard policy blocks always win.
    """
    if not isinstance(tool, Mapping):
        return TOOL_STATUS_REJECTED

    if get_policy_flags(tool):
        return TOOL_STATUS_REJECTED

    explicit = _get_explicit_status(tool)
    if explicit is not None:
        return explicit

    action = get_editorial_action(tool)
    if action == EDITORIAL_ACTION_DELETE:
        return TOOL_STATUS_REJECTED
    if action == EDITORIAL_ACTION_NEEDS_REVIEW:
        return TOOL_STATUS_CANDIDATE
    if action == EDITORIAL_ACTION_NOINDEX or _has_legacy_noindex_flag(tool):
        return TOOL_STATUS_HIDDEN
    return TOOL_STATUS_PUBLISHED


def get_tool_noindex_status(tool: Mapping[str, Any] | None) -> bool:
    """Check if a tool should be publicly accessible but excluded from indexing."""
    return get_tool_status(tool) == TOOL_STATUS_HIDDEN


def is_public_tool(tool: Mapping[str, Any] | None) -> bool:
    """Return whether a tool should be accessible via its direct page."""
    return get_tool_status(tool) in {TOOL_STATUS_PUBLISHED, TOOL_STATUS_HIDDEN}


def is_indexable_tool(tool: Mapping[str, Any] | None) -> bool:
    """Return whether a tool should appear in public listings and sitemaps."""
    return get_tool_status(tool) == TOOL_STATUS_PUBLISHED
