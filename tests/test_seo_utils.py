from ai_tools_website.v1.seo_utils import generate_comparison_slug
from ai_tools_website.v1.seo_utils import generate_tool_slug


def test_generate_tool_slug_removes_stopwords_and_enforces_length():
    slug = generate_tool_slug("The Amazing AI Tool For Developers")
    assert slug == "amazing-developers"


def test_generate_tool_slug_prefers_vendor_prefix():
    slug = generate_tool_slug("Copilot", vendor_name="GitHub")
    assert slug == "github-copilot"


def test_generate_tool_slug_uses_disambiguator_when_needed():
    # Empty name should fall back to disambiguator
    slug = generate_tool_slug("", disambiguator="Widget-Cloud")
    assert slug == "widget-cloud"


def test_generate_comparison_slug_can_use_provided_slugs():
    slug = generate_comparison_slug(
        "Tool One",
        "Tool Two",
        tool1_slug="tool-one",
        tool2_slug="tool-two",
    )
    assert slug == "tool-one-vs-tool-two"
