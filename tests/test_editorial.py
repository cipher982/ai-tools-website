from ai_tools_website.v1.editorial import EDITORIAL_ACTION_DELETE
from ai_tools_website.v1.editorial import EDITORIAL_ACTION_KEEP
from ai_tools_website.v1.editorial import EDITORIAL_ACTION_NOINDEX
from ai_tools_website.v1.editorial import TOOL_STATUS_CANDIDATE
from ai_tools_website.v1.editorial import TOOL_STATUS_HIDDEN
from ai_tools_website.v1.editorial import TOOL_STATUS_PUBLISHED
from ai_tools_website.v1.editorial import TOOL_STATUS_REJECTED
from ai_tools_website.v1.editorial import get_editorial_action
from ai_tools_website.v1.editorial import get_policy_flags
from ai_tools_website.v1.editorial import get_tool_noindex_status
from ai_tools_website.v1.editorial import get_tool_status
from ai_tools_website.v1.editorial import is_indexable_tool
from ai_tools_website.v1.editorial import is_public_tool


def test_get_editorial_action_defaults_to_keep_for_legacy_records():
    assert get_editorial_action({"name": "Legacy Tool"}) == EDITORIAL_ACTION_KEEP


def test_get_editorial_action_supports_nested_editorial_schema():
    tool = {"editorial": {"action": "NoIndex"}}
    assert get_editorial_action(tool) == EDITORIAL_ACTION_NOINDEX


def test_get_editorial_action_supports_root_level_action():
    tool = {"action": "delete"}
    assert get_editorial_action(tool) == EDITORIAL_ACTION_DELETE


def test_public_and_indexable_status_respect_editorial_actions():
    assert is_public_tool({"action": "keep"}) is True
    assert is_public_tool({"action": "noindex"}) is True
    assert is_public_tool({"action": "delete"}) is False
    assert is_public_tool({"action": "needs_review"}) is False

    assert is_indexable_tool({"action": "keep"}) is True
    assert is_indexable_tool({"action": "noindex"}) is False
    assert is_indexable_tool({"action": "delete"}) is False
    assert is_indexable_tool({"action": "needs_review"}) is False


def test_get_tool_noindex_status_respects_editorial_and_legacy_flags():
    assert get_tool_noindex_status({"action": "noindex"}) is True
    assert get_tool_noindex_status({"noindex": True}) is True
    assert get_tool_noindex_status({"enhanced_content_v2": {"tier": "noindex"}}) is True
    assert get_tool_noindex_status({"_tier": "noindex"}) is True
    assert get_tool_noindex_status({"action": "keep"}) is False


def test_get_tool_status_supports_explicit_visibility_status():
    assert get_tool_status({"status": "published"}) == TOOL_STATUS_PUBLISHED
    assert get_tool_status({"status": "hidden"}) == TOOL_STATUS_HIDDEN
    assert get_tool_status({"status": "candidate"}) == TOOL_STATUS_CANDIDATE
    assert get_tool_status({"status": "rejected"}) == TOOL_STATUS_REJECTED


def test_policy_flags_reject_obvious_junk_tools():
    blocked = {
        "name": "PrimeAIM",
        "description": "AI-powered aim assist for shooter games with ESP overlays.",
        "url": "https://example.com/primeaim",
    }
    flags = get_policy_flags(blocked)

    assert "aim assist" in flags
    assert get_tool_status(blocked) == TOOL_STATUS_REJECTED
    assert is_public_tool(blocked) is False
    assert is_indexable_tool(blocked) is False


def test_policy_flags_reject_uncensored_and_nsfw_terms():
    blocked = {
        "name": "Flux-uncensored",
        "description": "NSFW text-to-image model.",
        "url": "https://example.com/flux-uncensored",
    }

    assert get_policy_flags(blocked) == ["nsfw", "uncensored"]
    assert get_tool_status(blocked) == TOOL_STATUS_REJECTED
