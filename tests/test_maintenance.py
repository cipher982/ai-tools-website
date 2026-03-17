import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

from ai_tools_website.v1 import maintenance
from ai_tools_website.v1.editorial_batch import EditorialBatchResult
from ai_tools_website.v1.editorial_batch import ReviewedToolResult
from ai_tools_website.v1.editorial_loop import EditorialLoopItemResult
from ai_tools_website.v1.editorial_loop import EditorialLoopResult
from ai_tools_website.v1.maintenance import CategoryChange
from ai_tools_website.v1.maintenance import RecategorizationChanges


class _DummySummary:
    def __init__(self):
        self.metrics = {}
        self.attributes = {}
        self.status = "success"
        self.error_type = None
        self.error_note = None

    def add_metric(self, name, value):
        self.metrics[name] = value

    def add_attribute(self, name, value):
        self.attributes[name] = value

    def mark_failed(self, *, error_type=None, note=None):
        self.status = "error"
        self.error_type = error_type
        self.error_note = note


def test_build_parser_accepts_editorial_review_options():
    parser = maintenance.build_parser()

    args = parser.parse_args(
        [
            "editorial-review",
            "--slug",
            "opencode",
            "--slug",
            "open-aimbot",
            "--max-per-run",
            "7",
            "--stale-after-days",
            "14",
            "--dry-run",
            "--force",
            "--no-web-search",
            "--json-output",
        ]
    )

    assert args.task == "editorial-review"
    assert args.slugs == ["opencode", "open-aimbot"]
    assert args.max_per_run == 7
    assert args.stale_after_days == 14
    assert args.dry_run is True
    assert args.force is True
    assert args.use_web_search is False
    assert args.json_output is True


def test_build_parser_accepts_editorial_loop_options():
    parser = maintenance.build_parser()

    args = parser.parse_args(
        [
            "editorial-loop",
            "--slug",
            "opencode",
            "--max-per-run",
            "5",
            "--content-max-per-run",
            "2",
            "--stale-after-days",
            "21",
            "--dry-run",
            "--force",
            "--no-web-search",
            "--json-output",
        ]
    )

    assert args.task == "editorial-loop"
    assert args.slugs == ["opencode"]
    assert args.max_per_run == 5
    assert args.content_max_per_run == 2
    assert args.stale_after_days == 21
    assert args.dry_run is True
    assert args.force is True
    assert args.use_web_search is False
    assert args.json_output is True


def test_editorial_review_database_forwards_args_and_records_summary(monkeypatch, capsys):
    summary = _DummySummary()
    recorded = {}

    @contextmanager
    def fake_pipeline_summary(name):
        recorded["pipeline"] = name
        yield summary

    result = EditorialBatchResult(
        selected=2,
        reviewed=1,
        updated=1,
        failed=1,
        dry_run=True,
        reviewed_slugs=["opencode"],
        failed_slugs=["open-aimbot"],
        missing_slugs=["missing-tool"],
        action_counts={"keep": 1},
        reviews=[ReviewedToolResult(slug="opencode", action="keep", why="Legitimate tool.")],
    )

    def fake_runner(**kwargs):
        recorded["runner_kwargs"] = kwargs
        return result

    monkeypatch.setattr(maintenance, "pipeline_summary", fake_pipeline_summary)
    monkeypatch.setattr(maintenance, "run_editorial_review_batch", fake_runner)

    returned = maintenance.editorial_review_database(
        max_per_run=5,
        slugs=["opencode", "missing-tool"],
        stale_after_days=21,
        dry_run=True,
        force=True,
        use_web_search=False,
        json_output=True,
    )

    captured = capsys.readouterr()
    assert returned == result
    assert recorded["pipeline"] == "maintenance_editorial_review"
    assert recorded["runner_kwargs"] == {
        "max_per_run": 5,
        "slugs": ["opencode", "missing-tool"],
        "stale_after_days": 21,
        "dry_run": True,
        "force": True,
        "use_web_search": False,
    }
    assert summary.metrics["selected"] == 2
    assert summary.metrics["reviewed"] == 1
    assert summary.metrics["updated"] == 1
    assert summary.metrics["failed"] == 1
    assert summary.metrics["action_keep"] == 1
    assert summary.attributes["requested_slugs"] == "opencode,missing-tool"
    assert summary.attributes["missing_slugs"] == "missing-tool"
    assert summary.status == "error"
    assert summary.error_type == "PartialFailure"
    assert summary.error_note == "1 editorial reviews failed"
    assert '"selected": 2' in captured.out


def test_dispatch_task_calls_editorial_review_database(monkeypatch):
    called = {}

    def fake_editorial_review_database(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(maintenance, "editorial_review_database", fake_editorial_review_database)

    args = argparse.Namespace(
        task="editorial-review",
        yes=False,
        max_per_run=3,
        slugs=["opencode"],
        stale_after_days=10,
        dry_run=True,
        force=False,
        use_web_search=True,
        json_output=False,
    )

    maintenance.dispatch_task(args)

    assert called == {
        "max_per_run": 3,
        "slugs": ["opencode"],
        "stale_after_days": 10,
        "dry_run": True,
        "force": False,
        "use_web_search": True,
        "json_output": False,
    }


def test_editorial_loop_database_forwards_args_and_records_summary(monkeypatch, capsys):
    summary = _DummySummary()
    recorded = {}

    @contextmanager
    def fake_pipeline_summary(name):
        recorded["pipeline"] = name
        yield summary

    result = EditorialLoopResult(
        selected=2,
        reviewed=2,
        updated=2,
        failed=0,
        enriched=1,
        dry_run=True,
        reviewed_slugs=["opencode", "builder-tool"],
        enriched_slugs=["opencode"],
        action_counts={"keep": 2},
        reason_counts={"missing_editorial": 2},
        items=[EditorialLoopItemResult(slug="opencode", reasons=["missing_editorial"], action="keep")],
    )

    def fake_runner(**kwargs):
        recorded["runner_kwargs"] = kwargs
        return result

    monkeypatch.setattr(maintenance, "pipeline_summary", fake_pipeline_summary)
    monkeypatch.setattr(maintenance, "run_editorial_loop", fake_runner)

    returned = maintenance.editorial_loop_database(
        max_per_run=4,
        content_max_per_run=2,
        slugs=["opencode"],
        stale_after_days=11,
        dry_run=True,
        force=True,
        use_web_search=False,
        json_output=True,
    )

    captured = capsys.readouterr()
    assert returned == result
    assert recorded["pipeline"] == "maintenance_editorial_loop"
    assert recorded["runner_kwargs"] == {
        "max_per_run": 4,
        "content_max_per_run": 2,
        "slugs": ["opencode"],
        "stale_after_days": 11,
        "dry_run": True,
        "force": True,
        "use_web_search": False,
    }
    assert summary.metrics["selected"] == 2
    assert summary.metrics["reviewed"] == 2
    assert summary.metrics["updated"] == 2
    assert summary.metrics["enriched"] == 1
    assert summary.metrics["failed"] == 0
    assert summary.metrics["action_keep"] == 2
    assert summary.attributes["requested_slugs"] == "opencode"
    assert '"selected": 2' in captured.out


def test_editorial_loop_database_marks_partial_failures(monkeypatch):
    summary = _DummySummary()

    @contextmanager
    def fake_pipeline_summary(name):
        yield summary

    result = EditorialLoopResult(
        selected=3,
        reviewed=2,
        updated=2,
        failed=1,
        enriched=0,
        content_failed=1,
        dry_run=True,
        reviewed_slugs=["good-tool"],
        failed_slugs=["bad-tool"],
        action_counts={"delete": 2},
        reason_counts={"suspicious": 3},
        items=[EditorialLoopItemResult(slug="bad-tool", reasons=["suspicious"], error="review_failed")],
    )

    monkeypatch.setattr(maintenance, "pipeline_summary", fake_pipeline_summary)
    monkeypatch.setattr(maintenance, "run_editorial_loop", lambda **kwargs: result)

    returned = maintenance.editorial_loop_database(dry_run=True)

    assert returned == result
    assert summary.status == "error"
    assert summary.error_type == "PartialFailure"
    assert summary.error_note == "1 editorial reviews failed; 1 content refreshes failed"


def test_dispatch_task_calls_editorial_loop_database(monkeypatch):
    called = {}

    def fake_editorial_loop_database(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(maintenance, "editorial_loop_database", fake_editorial_loop_database)

    args = argparse.Namespace(
        task="editorial-loop",
        yes=False,
        max_per_run=6,
        content_max_per_run=3,
        slugs=["opencode"],
        stale_after_days=9,
        dry_run=True,
        force=False,
        use_web_search=True,
        json_output=False,
    )

    maintenance.dispatch_task(args)

    assert called == {
        "max_per_run": 6,
        "content_max_per_run": 3,
        "slugs": ["opencode"],
        "stale_after_days": 9,
        "dry_run": True,
        "force": False,
        "use_web_search": True,
        "json_output": False,
    }


def test_recategorize_database_only_touches_changed_tools(monkeypatch):
    summary = _DummySummary()
    saved = {}
    fixed_now = "2026-03-17T12:00:00+00:00"

    class _FrozenDateTime:
        @staticmethod
        def now(_tz):
            return datetime.fromisoformat(fixed_now)

    class _FakeParseResult:
        def __init__(self):
            self.choices = [self]
            self.message = self
            self.parsed = RecategorizationChanges(
                category_changes=[
                    CategoryChange.model_validate(
                        {
                            "from": "Developer Tools",
                            "to": "Code Assistants",
                            "reason": "More specific fixed taxonomy.",
                        }
                    )
                ]
            )

    @contextmanager
    def fake_pipeline_summary(name):
        assert name == "maintenance"
        yield summary

    current_tools = {
        "tools": [
            {
                "name": "Tool A",
                "category": "Developer Tools",
                "description": "Moves to the new category.",
            },
            {
                "name": "Tool B",
                "category": "Image Generation",
                "description": "Should stay untouched.",
                "updated_at": "2026-02-01T00:00:00+00:00",
            },
        ]
    }

    def fake_save_tools(payload):
        saved["payload"] = payload

    monkeypatch.setattr(maintenance, "datetime", _FrozenDateTime)
    monkeypatch.setattr(maintenance, "load_tools", lambda: current_tools)
    monkeypatch.setattr(
        maintenance,
        "client",
        SimpleNamespace(
            beta=SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kwargs: _FakeParseResult()))
            )
        ),
    )
    monkeypatch.setattr(maintenance, "save_tools_with_retry", fake_save_tools)
    monkeypatch.setattr(maintenance, "pipeline_summary", fake_pipeline_summary)

    asyncio.run(maintenance.recategorize_database(auto_accept=True))

    saved_tools = saved["payload"]["tools"]
    assert saved_tools[0]["category"] == "Code Assistants"
    assert saved_tools[0]["updated_at"] == fixed_now
    assert "last_reviewed_at" not in saved_tools[0]
    assert "last_indexed_at" not in saved_tools[0]

    assert saved_tools[1]["category"] == "Image Generation"
    assert saved_tools[1]["updated_at"] == "2026-02-01T00:00:00+00:00"
    assert "last_reviewed_at" not in saved_tools[1]
    assert "last_indexed_at" not in saved_tools[1]
