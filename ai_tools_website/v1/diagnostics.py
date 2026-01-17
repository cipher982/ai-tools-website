"""Diagnostics and profiling helpers for the ai-tools pipeline."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from datetime import timezone

import click

from ai_tools_website.v1.data_manager import load_tools
from ai_tools_website.v1.quality_tiers import should_refresh
from ai_tools_website.v1.quality_tiers import tier_all_tools
from ai_tools_website.v1.storage import use_local_storage

logger = logging.getLogger(__name__)


def _summarize_tools(tools: list[dict]) -> dict:
    missing_v2 = 0
    with_v2 = 0
    ages = []

    for tool in tools:
        if tool.get("enhanced_content_v2"):
            with_v2 += 1
        else:
            missing_v2 += 1
        ts = tool.get("enhanced_at_v2")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                ages.append((datetime.now(timezone.utc) - dt).days)
            except Exception:
                pass

    summary = {
        "tools_total": len(tools),
        "with_v2": with_v2,
        "missing_v2": missing_v2,
    }
    if ages:
        summary.update(
            {
                "enhanced_at_v2_days_min": min(ages),
                "enhanced_at_v2_days_max": max(ages),
                "enhanced_at_v2_days_avg": round(sum(ages) / len(ages), 1),
            }
        )
    return summary


def _stale_counts(tiered: dict[str, list[dict]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for tier_name, tier_tools in tiered.items():
        stale = 0
        for tool in tier_tools:
            if should_refresh(tool, tier_name):
                stale += 1
        counts[tier_name] = {"total": len(tier_tools), "stale": stale}
    return counts


@click.command()
@click.option("--check-umami", is_flag=True, help="Fetch Umami traffic stats")
def main(check_umami: bool) -> None:
    """Run lightweight diagnostics without LLM calls."""
    t0 = time.perf_counter()
    tools_doc = load_tools()
    t1 = time.perf_counter()

    tools = tools_doc.get("tools", [])
    tiered = tier_all_tools(tools)
    t2 = time.perf_counter()

    print(f"storage_backend={'local' if use_local_storage() else 'minio'}")
    print(f"load_tools_seconds={t1 - t0:.3f}")
    print(f"tier_all_tools_seconds={t2 - t1:.3f}")

    summary = _summarize_tools(tools)
    for key, value in summary.items():
        print(f"{key}={value}")

    for tier_name, stats in _stale_counts(tiered).items():
        print(f"{tier_name}: total={stats['total']} stale={stats['stale']}")

    if check_umami:
        from ai_tools_website.v1.data_aggregators.umami_aggregator import fetch_traffic_stats

        print("checking_umami=true")
        stats = asyncio.run(fetch_traffic_stats())
        print(f"umami_tools_with_traffic={len(stats)}")


if __name__ == "__main__":
    main()
