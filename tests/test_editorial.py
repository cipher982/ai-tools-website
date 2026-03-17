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


def test_policy_flags_reject_nsfw_undressing_tools():
    blocked = {
        "name": "UndressAI",
        "description": "AI-powered undressing tool that generates realistic undressed versions.",
        "url": "https://example.com/undressai",
    }

    flags = get_policy_flags(blocked)

    assert "undressai" in flags
    assert "undressed versions" in flags
    assert "undressing tool" in flags
    assert get_tool_status(blocked) == TOOL_STATUS_REJECTED


def test_policy_flags_reject_cheat_and_executor_language():
    blocked = {
        "name": "Aimmy-V2",
        "description": "AI-based aim alignment with auto-trigger for FPS games.",
        "url": "https://example.com/aimmy-v2",
    }

    flags = get_policy_flags(blocked)

    assert "aim alignment" in flags
    assert "auto-trigger" in flags
    assert "aimmy" in flags
    assert get_tool_status(blocked) == TOOL_STATUS_REJECTED


def test_policy_flags_reject_script_executors_and_unlocker_bait():
    executor = {
        "name": "Xeno Executor",
        "description": "Roblox script executor with anti-ban features.",
        "url": "https://example.com/xeno-executor",
    }
    unlocker = {
        "name": "Photoshop AI Tools Unlocked Edition",
        "description": "Unlocked edition of Photoshop AI tools for premium features.",
        "url": "https://example.com/photoshop-unlocked-edition",
    }

    assert "script executor" in get_policy_flags(executor)
    assert "anti-ban" in get_policy_flags(executor)
    assert get_tool_status(executor) == TOOL_STATUS_REJECTED

    assert "unlocked edition" in get_policy_flags(unlocker)
    assert get_tool_status(unlocker) == TOOL_STATUS_REJECTED
