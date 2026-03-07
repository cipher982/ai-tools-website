import json
from datetime import datetime
from datetime import timezone

from click.testing import CliRunner

from ai_tools_website.v1 import editorial_batch
from ai_tools_website.v1.editorial_agent import EditorialReview

FIXED_NOW = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)


def build_tool(
    slug: str,
    *,
    action: str | None = None,
    reviewed_at: str | None = None,
    editorial_action: str | None = None,
) -> dict:
    tool = {
        "name": slug.replace("-", " ").title(),
        "slug": slug,
        "category": "Code Assistants",
        "description": f"{slug} description",
        "url": f"https://example.com/{slug}",
    }
    if action is not None:
        tool["action"] = action
    if reviewed_at is not None:
        tool["last_reviewed_at"] = reviewed_at
    if editorial_action is not None or reviewed_at is not None:
        tool["editorial"] = {}
        if editorial_action is not None:
            tool["editorial"]["action"] = editorial_action
        if reviewed_at is not None:
            tool["editorial"]["reviewed_at"] = reviewed_at
    return tool


def make_review(action: str, why: str) -> EditorialReview:
    return EditorialReview(
        action=action,
        why=why,
        ideal_user="Builders",
        not_for="Scammy workflows",
        decision_value=["Specific value"],
        page_angle="Useful angle",
        suggested_sections=["Why choose it", "Why skip it"],
        comparison_candidates=["aider"],
        confidence=0.8,
    )


def test_normalize_requested_slugs_deduplicates_and_trims():
    assert editorial_batch.normalize_requested_slugs([" OpenCode ", "opencode", "", "Aider"]) == [
        "opencode",
        "aider",
    ]


def test_get_tool_reviewed_at_prefers_editorial_timestamp():
    tool = build_tool(
        "opencode",
        reviewed_at="2026-02-01T00:00:00+00:00",
        editorial_action="keep",
    )
    tool["last_reviewed_at"] = "2026-01-01T00:00:00+00:00"

    reviewed_at = editorial_batch.get_tool_reviewed_at(tool)

    assert reviewed_at == datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)


def test_select_tools_prioritizes_needs_review_then_unreviewed_then_stale():
    tools = [
        build_tool("fresh-keep", action="keep", reviewed_at="2026-03-05T00:00:00+00:00", editorial_action="keep"),
        build_tool("deleted-tool", action="delete"),
        build_tool(
            "needs-review",
            action="needs_review",
            reviewed_at="2026-03-06T00:00:00+00:00",
            editorial_action="needs_review",
        ),
        build_tool("unreviewed-tool", action="keep"),
        build_tool("stale-tool", action="keep", reviewed_at="2025-12-01T00:00:00+00:00", editorial_action="keep"),
    ]

    selected = editorial_batch.select_tools_for_editorial_review(
        tools,
        max_per_run=5,
        stale_after_days=30,
        now=FIXED_NOW,
    )

    assert [item.slug for item in selected] == ["needs-review", "unreviewed-tool", "stale-tool"]


def test_select_tools_respects_explicit_slug_order_and_manual_override():
    tools = [
        build_tool("deleted-tool", action="delete"),
        build_tool("fresh-keep", action="keep", reviewed_at="2026-03-06T00:00:00+00:00", editorial_action="keep"),
    ]

    selected = editorial_batch.select_tools_for_editorial_review(
        tools,
        max_per_run=2,
        slugs=["fresh-keep", "deleted-tool"],
        now=FIXED_NOW,
    )

    assert [item.slug for item in selected] == ["fresh-keep", "deleted-tool"]


def test_run_editorial_review_batch_saves_updates_and_counts_actions():
    tools_doc = {
        "tools": [
            build_tool("opencode"),
            build_tool("open-aimbot"),
        ]
    }
    saved_payloads: list[dict] = []

    def fake_reviewer(tool, *, model, use_web_search):
        assert model == "glm-test"
        assert use_web_search is False
        if tool["slug"] == "opencode":
            return make_review("keep", "Legitimate builder tool.")
        return make_review("delete", "Cheat tool.")

    def fake_loader():
        return tools_doc

    def fake_saver(payload):
        saved_payloads.append(json.loads(json.dumps(payload)))

    result = editorial_batch.run_editorial_review_batch(
        slugs=["opencode", "open-aimbot"],
        force=True,
        use_web_search=False,
        model="glm-test",
        reviewer=fake_reviewer,
        loader=fake_loader,
        saver=fake_saver,
        now=FIXED_NOW,
    )

    assert result.selected == 2
    assert result.reviewed == 2
    assert result.updated == 2
    assert result.failed == 0
    assert result.reviewed_slugs == ["opencode", "open-aimbot"]
    assert result.action_counts == {"keep": 1, "delete": 1}
    assert [review.slug for review in result.reviews] == ["opencode", "open-aimbot"]
    assert result.reviews[1].action == "delete"
    assert result.reviews[1].why == "Cheat tool."
    assert len(saved_payloads) == 1
    assert saved_payloads[0]["tools"][0]["action"] == "keep"
    assert saved_payloads[0]["tools"][1]["action"] == "delete"
    assert saved_payloads[0]["tools"][1]["editorial"]["why"] == "Cheat tool."


def test_run_editorial_review_batch_dry_run_skips_save():
    tools_doc = {"tools": [build_tool("opencode")]}
    save_calls: list[int] = []

    def fake_saver(payload):
        save_calls.append(len(payload["tools"]))

    result = editorial_batch.run_editorial_review_batch(
        slugs=["opencode"],
        dry_run=True,
        model="glm-test",
        reviewer=lambda tool, **kwargs: make_review("keep", "Legitimate tool."),
        loader=lambda: tools_doc,
        saver=fake_saver,
        now=FIXED_NOW,
    )

    assert result.reviewed == 1
    assert result.updated == 1
    assert save_calls == []


def test_run_editorial_review_batch_records_failures_and_continues():
    tools_doc = {"tools": [build_tool("broken-tool"), build_tool("opencode")]}
    saved_payloads: list[dict] = []

    def fake_reviewer(tool, **kwargs):
        if tool["slug"] == "broken-tool":
            raise RuntimeError("boom")
        return make_review("keep", "Still worth keeping.")

    result = editorial_batch.run_editorial_review_batch(
        slugs=["broken-tool", "opencode"],
        force=True,
        model="glm-test",
        reviewer=fake_reviewer,
        loader=lambda: tools_doc,
        saver=lambda payload: saved_payloads.append(json.loads(json.dumps(payload))),
        now=FIXED_NOW,
    )

    assert result.selected == 2
    assert result.reviewed == 1
    assert result.updated == 1
    assert result.failed == 1
    assert result.failed_slugs == ["broken-tool"]
    assert result.reviews[0].slug == "broken-tool"
    assert result.reviews[0].error == "review_failed"
    assert result.reviews[1].action == "keep"
    assert len(saved_payloads) == 1
    assert saved_payloads[0]["tools"][1]["action"] == "keep"


def test_run_editorial_review_batch_reports_missing_slugs_without_crashing():
    tools_doc = {"tools": [build_tool("opencode")]}

    result = editorial_batch.run_editorial_review_batch(
        slugs=["missing-tool", "opencode"],
        model="glm-test",
        reviewer=lambda tool, **kwargs: make_review("keep", "Legitimate tool."),
        loader=lambda: tools_doc,
        saver=lambda payload: None,
        now=FIXED_NOW,
    )

    assert result.selected == 1
    assert result.missing_slugs == ["missing-tool"]
    assert result.reviewed_slugs == ["opencode"]


def test_cli_reviews_local_tools_file(tmp_path, monkeypatch):
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(json.dumps({"tools": [build_tool("opencode")], "last_updated": ""}, indent=2))

    monkeypatch.setenv("AITOOLS_STORAGE_BACKEND", "local")
    monkeypatch.setenv("TOOLS_FILE", str(tools_path))
    monkeypatch.setattr(editorial_batch, "setup_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(editorial_batch, "resolve_editorial_review_model", lambda: "glm-test")
    monkeypatch.setattr(
        editorial_batch,
        "review_tool",
        lambda tool, **kwargs: make_review("keep", "Legitimate builder tool."),
    )

    runner = CliRunner()
    result = runner.invoke(editorial_batch.main, ["--slug", "opencode", "--no-web-search"])

    assert result.exit_code == 0
    assert "selected=1 reviewed=1 updated=1 failed=0 dry_run=false" in result.output
    assert "actions=keep:1" in result.output

    saved = json.loads(tools_path.read_text())
    assert saved["tools"][0]["action"] == "keep"
    assert saved["tools"][0]["editorial"]["why"] == "Legitimate builder tool."


def test_cli_json_output_includes_review_details(tmp_path, monkeypatch):
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(json.dumps({"tools": [build_tool("opencode")], "last_updated": ""}, indent=2))

    monkeypatch.setenv("AITOOLS_STORAGE_BACKEND", "local")
    monkeypatch.setenv("TOOLS_FILE", str(tools_path))
    monkeypatch.setattr(editorial_batch, "setup_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(editorial_batch, "resolve_editorial_review_model", lambda: "glm-test")
    monkeypatch.setattr(
        editorial_batch,
        "review_tool",
        lambda tool, **kwargs: make_review("keep", "Legitimate builder tool."),
    )

    runner = CliRunner()
    result = runner.invoke(editorial_batch.main, ["--slug", "opencode", "--dry-run", "--json-output"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["selected"] == 1
    assert payload["dry_run"] is True
    assert payload["reviews"][0]["slug"] == "opencode"
    assert payload["reviews"][0]["action"] == "keep"
    assert payload["reviews"][0]["why"] == "Legitimate builder tool."


def test_cli_dry_run_leaves_local_tools_file_unchanged(tmp_path, monkeypatch):
    tools_path = tmp_path / "tools.json"
    original_payload = {"tools": [build_tool("opencode")], "last_updated": ""}
    tools_path.write_text(json.dumps(original_payload, indent=2))

    monkeypatch.setenv("AITOOLS_STORAGE_BACKEND", "local")
    monkeypatch.setenv("TOOLS_FILE", str(tools_path))
    monkeypatch.setattr(editorial_batch, "setup_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(editorial_batch, "resolve_editorial_review_model", lambda: "glm-test")
    monkeypatch.setattr(
        editorial_batch,
        "review_tool",
        lambda tool, **kwargs: make_review("noindex", "Useful, but too niche."),
    )

    runner = CliRunner()
    result = runner.invoke(editorial_batch.main, ["--slug", "opencode", "--dry-run"])

    assert result.exit_code == 0
    assert "dry_run=true" in result.output
    assert json.loads(tools_path.read_text()) == original_payload
