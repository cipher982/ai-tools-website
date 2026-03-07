"""Editorial visibility helpers for v2 action gating."""

from __future__ import annotations

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


def get_tool_noindex_status(tool: Mapping[str, Any] | None) -> bool:
    """Check if a tool should be publicly accessible but excluded from indexing."""
    if not isinstance(tool, Mapping):
        return False

    if get_editorial_action(tool) == EDITORIAL_ACTION_NOINDEX:
        return True

    enhanced_v2 = tool.get("enhanced_content_v2")
    tier = None
    if isinstance(enhanced_v2, Mapping):
        tier = enhanced_v2.get("tier")
    if tier is None:
        tier = tool.get("_tier")
    if tier == "noindex":
        return True

    return tool.get("noindex") is True


def is_public_tool(tool: Mapping[str, Any] | None) -> bool:
    """Return whether a tool should be accessible via its direct page."""
    return get_editorial_action(tool) in {EDITORIAL_ACTION_KEEP, EDITORIAL_ACTION_NOINDEX}


def is_indexable_tool(tool: Mapping[str, Any] | None) -> bool:
    """Return whether a tool should appear in public listings and sitemaps."""
    return get_editorial_action(tool) == EDITORIAL_ACTION_KEEP and not get_tool_noindex_status(tool)
