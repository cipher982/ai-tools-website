from datetime import datetime
from datetime import timezone

from ai_tools_website.v1.editorial_agent import EditorialReview
from ai_tools_website.v1.editorial_loop import DEFAULT_PRUNE_CONFIDENCE
from ai_tools_website.v1.editorial_loop import find_suspicious_keywords
from ai_tools_website.v1.editorial_loop import run_editorial_loop
from ai_tools_website.v1.editorial_loop import select_tools_for_editorial_loop


async def _fake_enhancer(tool):
    return {
        "overview": {"body": f"Enhanced overview for {tool['name']}"},
        "key_features": {"items": ["Feature A", "Feature B"]},
    }


def _tierer(tools):
    for index, tool in enumerate(tools):
        tool.setdefault("_tier", "tier2" if index == 0 else "tier3")
        tool.setdefault("_importance_score", 90 - index)
    return {"tier1": [], "tier2": [], "tier3": tools, "noindex": []}


def test_find_suspicious_keywords_ignores_partial_word_false_positives():
    assert (
        find_suspicious_keywords(
            {
                "name": "Vercel AI Chatbot",
                "description": "A full-featured, hackable chatbot framework.",
                "url": "https://github.com/vercel/ai-chatbot",
            }
        )
        == []
    )
    assert (
        find_suspicious_keywords(
            {
                "name": "Grok 3 ai",
                "description": "Flagship reasoning model.",
                "url": "https://huggingface.co/blog/LLMhacker/grok-3-ai",
            }
        )
        == []
    )


def test_find_suspicious_keywords_matches_real_risky_terms():
    assert find_suspicious_keywords(
        {
            "name": "Open-Aimbot",
            "description": "Silent aim cheat with bypass support.",
            "url": "https://github.com/example/open-aimbot",
        }
    ) == ["aimbot", "cheat", "bypass"]
    assert find_suspicious_keywords(
        {
            "name": "Aviator Prediction App",
            "description": "Betting predictor for aviator players.",
            "url": "https://example.com/aviator-prediction",
        }
    ) == ["aviator", "betting", "predictor", "prediction"]


def test_select_tools_for_editorial_loop_prioritizes_suspicious_and_missing_editorial():
    tools = [
        {
            "name": "Open Aimbot",
            "slug": "open-aimbot",
            "description": "Silent aim cheat for Roblox exploitation.",
        },
        {
            "name": "Builder Tool",
            "slug": "builder-tool",
            "description": "Legitimate tool for developers.",
        },
        {
            "name": "Legacy Reviewed",
            "slug": "legacy-reviewed",
            "description": "Already reviewed tool.",
            "editorial": {"action": "keep", "why": "Already good", "reviewed_at": "2026-03-01T00:00:00+00:00"},
            "enhanced_content_v2": {"overview": {"body": "ready"}},
        },
    ]

    selected = select_tools_for_editorial_loop(
        tools,
        max_per_run=2,
        stale_after_days=30,
        tierer=_tierer,
        content_needed_fn=lambda tool, force: False,
        now=datetime(2026, 3, 8, tzinfo=timezone.utc),
    )

    assert [candidate.slug for candidate in selected] == ["open-aimbot", "builder-tool"]
    assert "suspicious" in selected[0].reasons
    assert "missing_editorial" in selected[1].reasons


def test_run_editorial_loop_reviews_and_enriches_keep_tools(monkeypatch):
    tools_doc = {
        "tools": [
            {
                "name": "Builder Tool",
                "slug": "builder-tool",
                "description": "Legitimate tool for developers.",
            }
        ]
    }
    saved = {}
    published = []
    refreshed = []

    monkeypatch.delenv("SERVICE_URL_WEB", raising=False)
    monkeypatch.setenv("BASE_PATH", "/aitools")

    def reviewer(tool, *, model, use_web_search):
        return EditorialReview(
            action="keep",
            why="Legitimate builder tool.",
            ideal_user="Developers",
            not_for="Gamblers",
            decision_value=["Useful workflow", "Clear builder value"],
            page_angle="A practical tool for builders.",
            suggested_sections=["Overview"],
            comparison_candidates=["Alt One"],
            confidence=0.86,
        )

    def saver(doc):
        saved["doc"] = doc

    def publisher(base_url):
        published.append(base_url)

    def cache_refresher(base_url):
        refreshed.append(base_url)

    result = run_editorial_loop(
        max_per_run=1,
        content_max_per_run=1,
        dry_run=False,
        use_web_search=False,
        reviewer=reviewer,
        enhancer=_fake_enhancer,
        loader=lambda: tools_doc,
        saver=saver,
        publisher=publisher,
        cache_refresher=cache_refresher,
        tierer=_tierer,
        content_needed_fn=lambda tool, force: True,
        now=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert result.selected == 1
    assert result.reviewed == 1
    assert result.updated == 1
    assert result.enriched == 1
    assert result.action_counts == {"keep": 1}
    assert result.items[0].content_action == "enhanced"
    updated_tool = saved["doc"]["tools"][0]
    assert updated_tool["action"] == "keep"
    assert updated_tool["editorial"]["why"] == "Legitimate builder tool."
    assert updated_tool["enhanced_content_v2"]["overview"]["body"] == "Enhanced overview for Builder Tool"
    assert published == ["https://drose.io/aitools"]
    assert refreshed == ["https://drose.io/aitools"]


def test_run_editorial_loop_auto_applies_high_confidence_delete_for_suspicious_tool():
    tools_doc = {
        "tools": [
            {
                "name": "Open Aimbot",
                "slug": "open-aimbot",
                "description": "Silent aim cheat for Roblox exploitation.",
            }
        ]
    }
    saved = {}

    def reviewer(tool, *, model, use_web_search):
        return EditorialReview(
            action="delete",
            why="Cheat tool.",
            ideal_user=None,
            not_for="Everyone",
            decision_value=[],
            page_angle=None,
            suggested_sections=[],
            comparison_candidates=[],
            confidence=0.99,
        )

    def saver(doc):
        saved["doc"] = doc

    result = run_editorial_loop(
        max_per_run=1,
        content_max_per_run=0,
        dry_run=False,
        use_web_search=False,
        reviewer=reviewer,
        enhancer=_fake_enhancer,
        loader=lambda: tools_doc,
        saver=saver,
        publisher=lambda base_url: None,
        cache_refresher=lambda base_url: None,
        tierer=_tierer,
        content_needed_fn=lambda tool, force: False,
        now=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert result.action_counts == {"delete": 1}
    assert result.items[0].raw_action == "delete"
    assert result.items[0].action == "delete"
    assert saved["doc"]["tools"][0]["action"] == "delete"


def test_run_editorial_loop_preserves_keep_for_low_confidence_prune():
    tools_doc = {
        "tools": [
            {
                "name": "Borderline Tool",
                "slug": "borderline-tool",
                "description": "Ambiguous niche tool.",
                "editorial": {"action": "keep", "why": "Legacy keep", "reviewed_at": "2026-03-01T00:00:00+00:00"},
            }
        ]
    }
    saved = {}

    def reviewer(tool, *, model, use_web_search):
        return EditorialReview(
            action="delete",
            why="Maybe delete.",
            ideal_user=None,
            not_for="Most users",
            decision_value=[],
            page_angle=None,
            suggested_sections=[],
            comparison_candidates=[],
            confidence=DEFAULT_PRUNE_CONFIDENCE - 0.2,
        )

    def saver(doc):
        saved["doc"] = doc

    result = run_editorial_loop(
        max_per_run=1,
        content_max_per_run=0,
        dry_run=False,
        use_web_search=False,
        reviewer=reviewer,
        enhancer=_fake_enhancer,
        loader=lambda: tools_doc,
        saver=saver,
        publisher=lambda base_url: None,
        cache_refresher=lambda base_url: None,
        tierer=_tierer,
        content_needed_fn=lambda tool, force: False,
        now=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert result.items[0].raw_action == "delete"
    assert result.items[0].action == "keep"
    assert saved["doc"]["tools"][0]["action"] == "keep"
