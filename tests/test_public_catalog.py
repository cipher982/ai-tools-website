from ai_tools_website.v1.public_catalog import build_public_tool_record
from ai_tools_website.v1.public_catalog import normalize_fixed_category
from ai_tools_website.v1.public_catalog import project_tools_document


def test_normalize_fixed_category_collapses_legacy_taxonomy():
    assert normalize_fixed_category("SDKs & Libraries") == "Developer Tools"
    assert normalize_fixed_category("Workflow Builders") == "Workflow Automation"
    assert normalize_fixed_category("Directories") == "Data and Research"


def test_build_public_tool_record_extracts_slim_public_fields():
    record = build_public_tool_record(
        {
            "id": "tool-1",
            "name": "Example Tool",
            "slug": "example-tool",
            "description": "A clean summary.",
            "url": "https://example.com/tool/",
            "category": "SDKs & Libraries",
            "tags": ["python", "agent"],
            "enhanced_content_v2": {
                "github_stats": {"url": "https://github.com/example/tool", "stars": 1234, "language": "Python"},
                "pypi_stats": {"downloads": {"last_month": 5000}},
            },
            "discovered_at": "2026-01-01T00:00:00+00:00",
            "last_enhanced_at": "2026-02-01T00:00:00+00:00",
        }
    )

    assert record["category"] == "Developer Tools"
    assert record["summary"] == "A clean summary."
    assert record["canonical_url"] == "https://example.com/tool"
    assert record["source_type"] == "github"
    assert record["source_url"] == "https://github.com/example/tool"
    assert record["metrics"] == {"github_stars": 1234, "pypi_downloads_30d": 5000}
    assert record["tags"] == ["python", "agent"]
    assert record["status"] == "published"
    assert record["content_hash"].startswith("sha256:")


def test_project_tools_document_drops_nonpublic_records_by_default():
    projected, counts = project_tools_document(
        {
            "tools": [
                {
                    "id": "tool-1",
                    "name": "Visible Tool",
                    "slug": "visible-tool",
                    "description": "Public.",
                    "url": "https://example.com/visible",
                    "category": "Developer Tools",
                },
                {
                    "id": "tool-2",
                    "name": "Review Tool",
                    "slug": "review-tool",
                    "description": "Needs review.",
                    "url": "https://example.com/review",
                    "category": "Developer Tools",
                    "action": "needs_review",
                },
                {
                    "id": "tool-3",
                    "name": "PrimeAIM",
                    "slug": "primeaim",
                    "description": "Aimbot with aim assist overlays.",
                    "url": "https://example.com/primeaim",
                    "category": "Gaming Tools",
                },
            ]
        }
    )

    assert [tool["slug"] for tool in projected] == ["visible-tool"]
    assert counts["published"] == 1
    assert counts["candidate"] == 1
    assert counts["rejected"] == 1
    assert counts["dropped"] == 2
