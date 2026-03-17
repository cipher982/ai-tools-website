from ai_tools_website.v1.data_manager import load_tools
from ai_tools_website.v1.data_manager import save_tools
from ai_tools_website.v1.storage import read_local_json
from ai_tools_website.v1.storage import write_local_json


def test_save_tools_preserves_last_updated_when_content_is_unchanged(tmp_path, monkeypatch):
    tools_path = tmp_path / "tools.json"
    monkeypatch.setenv("AITOOLS_STORAGE_BACKEND", "local")
    monkeypatch.setenv("TOOLS_FILE", str(tools_path))

    original = {
        "last_updated": "2026-03-01T00:00:00+00:00",
        "tools": [
            {
                "id": "tool-1",
                "name": "Example Tool",
                "slug": "example-tool",
                "description": "Original description.",
                "url": "https://example.com",
                "category": "Developer Tools",
            }
        ],
    }
    write_local_json(tools_path, original)

    loaded = load_tools()
    save_tools(loaded)

    saved = read_local_json(tools_path, {})
    assert saved["tools"] == original["tools"]
    assert saved["last_updated"] == original["last_updated"]


def test_save_tools_updates_last_updated_when_content_changes(tmp_path, monkeypatch):
    tools_path = tmp_path / "tools.json"
    monkeypatch.setenv("AITOOLS_STORAGE_BACKEND", "local")
    monkeypatch.setenv("TOOLS_FILE", str(tools_path))

    original = {
        "last_updated": "2026-03-01T00:00:00+00:00",
        "tools": [
            {
                "id": "tool-1",
                "name": "Example Tool",
                "slug": "example-tool",
                "description": "Original description.",
                "url": "https://example.com",
                "category": "Developer Tools",
            }
        ],
    }
    write_local_json(tools_path, original)

    loaded = load_tools()
    loaded["tools"][0]["description"] = "Updated description."
    save_tools(loaded)

    saved = read_local_json(tools_path, {})
    assert saved["tools"][0]["description"] == "Updated description."
    assert saved["last_updated"] != original["last_updated"]
