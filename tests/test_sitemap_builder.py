from xml.etree import ElementTree

from ai_tools_website.v1.sitemap_builder import build_sitemaps


def _example_tools_dataset():
    return {
        "last_updated": "2025-10-10T12:00:00+00:00",
        "tools": [
            {
                "id": "tool-1",
                "name": "Example Tool",
                "slug": "example-tool",
                "category": "Developer Tools",
                "discovered_at": "2025-09-15T00:00:00+00:00",
                "last_reviewed_at": "2025-10-09T00:00:00+00:00",
                "last_enhanced_at": "2025-10-08T00:00:00+00:00",
                "last_indexed_at": "2025-10-09T00:00:00+00:00",
                "comparisons": {
                    "example_tool_vs_other_tool": {
                        "slug": "example-tool-vs-other-tool",
                        "last_generated_at": "2025-10-07T00:00:00+00:00",
                    }
                },
            }
        ],
        "category_metadata": {
            "developer-tools": {
                "name": "Developer Tools",
                "slug": "developer-tools",
                "last_rebuilt_at": "2025-10-09T00:00:00+00:00",
            }
        },
    }


def test_build_sitemaps_produces_expected_sections():
    data = _example_tools_dataset()
    base_url = "https://example.com/aitools"

    sitemaps = build_sitemaps(data, base_url)

    assert "sitemap-index.xml" in sitemaps
    assert "sitemap-tools.xml" in sitemaps
    assert "sitemap-categories.xml" in sitemaps
    assert "sitemap-comparisons.xml" in sitemaps

    index_root = ElementTree.fromstring(sitemaps["sitemap-index.xml"])
    sitemap_locs = {elem.findtext("{http://www.sitemaps.org/schemas/sitemap/0.9}loc") for elem in index_root}
    assert f"{base_url}/sitemaps/sitemap-tools.xml" in sitemap_locs

    tools_root = ElementTree.fromstring(sitemaps["sitemap-tools.xml"])
    tool_locs = {elem.findtext("{http://www.sitemaps.org/schemas/sitemap/0.9}loc") for elem in tools_root}
    assert f"{base_url}/tools/example-tool" in tool_locs

    comparisons_root = ElementTree.fromstring(sitemaps["sitemap-comparisons.xml"])
    comparison_locs = {elem.findtext("{http://www.sitemaps.org/schemas/sitemap/0.9}loc") for elem in comparisons_root}
    assert f"{base_url}/compare/example-tool-vs-other-tool" in comparison_locs
