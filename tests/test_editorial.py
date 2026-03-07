from ai_tools_website.v1.editorial import EDITORIAL_ACTION_DELETE
from ai_tools_website.v1.editorial import EDITORIAL_ACTION_KEEP
from ai_tools_website.v1.editorial import EDITORIAL_ACTION_NOINDEX
from ai_tools_website.v1.editorial import get_editorial_action
from ai_tools_website.v1.editorial import get_tool_noindex_status
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
