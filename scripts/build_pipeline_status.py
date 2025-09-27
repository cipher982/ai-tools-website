#!/usr/bin/env python3
"""Generate a static pipeline status snapshot from structured log lines."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Dict
from typing import Iterable
from typing import Optional

SUMMARY_PREFIX = "PIPELINE_SUMMARY"
DEFAULT_PIPELINES = ["discovery", "maintenance", "enhancement"]
STALE_THRESHOLD = timedelta(hours=6)


def parse_summary(line: str) -> Optional[Dict]:
    """Extract the JSON payload from a summary log line."""
    if SUMMARY_PREFIX not in line:
        return None
    try:
        _, payload = line.split(f"{SUMMARY_PREFIX} ", 1)
    except ValueError:
        return None
    try:
        return json.loads(payload.strip())
    except json.JSONDecodeError:
        return None


def collect_latest(lines: Iterable[str], pipelines: Iterable[str]) -> Dict[str, Dict]:
    """Return the most recent summary payload per pipeline."""
    targets = set(pipelines)
    seen: Dict[str, Dict] = {}
    for raw in reversed(list(lines)):
        summary = parse_summary(raw)
        if not summary:
            continue
        pipeline = summary.get("pipeline")
        if not pipeline or pipeline not in targets:
            continue
        if pipeline in seen:
            continue
        seen[pipeline] = summary
        if len(seen) == len(targets):
            break
    return seen


def build_snapshot(latest: Dict[str, Dict], pipelines: Iterable[str]) -> Dict:
    now = datetime.now(timezone.utc)
    snapshot = {
        "generated_at": now.isoformat(),
        "pipelines": [],
    }

    for pipeline in pipelines:
        entry = latest.get(pipeline)
        if not entry:
            snapshot["pipelines"].append(
                {
                    "pipeline": pipeline,
                    "status": "missing",
                }
            )
            continue

        finished_raw = entry.get("finished_at")
        finished_dt: Optional[datetime] = None
        if isinstance(finished_raw, str):
            try:
                finished_dt = datetime.fromisoformat(finished_raw)
            except ValueError:
                finished_dt = None

        stale = False
        if finished_dt and now - finished_dt > STALE_THRESHOLD:
            stale = True

        snapshot["pipelines"].append(
            {
                "pipeline": pipeline,
                "status": entry.get("status", "unknown"),
                "started_at": entry.get("started_at"),
                "finished_at": finished_raw,
                "duration_seconds": entry.get("duration_seconds"),
                "stale": stale,
                "metrics": entry.get("metrics", {}),
                "attributes": entry.get("attributes", {}),
                "error_type": entry.get("error_type"),
                "error_note": entry.get("error_note"),
            }
        )

    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Build pipeline status snapshot from logs")
    parser.add_argument(
        "--log-file",
        default="logs/ai_tools.log",
        type=Path,
        help="Path to the log file containing summary lines",
    )
    parser.add_argument(
        "--output",
        default=Path("ai_tools_website/v1/static/pipeline_status.json"),
        type=Path,
        help="Destination for the produced snapshot",
    )
    parser.add_argument(
        "--pipelines",
        nargs="*",
        default=DEFAULT_PIPELINES,
        help="Pipeline identifiers to include in the snapshot",
    )

    args = parser.parse_args()

    if args.log_file.exists():
        lines = args.log_file.read_text().splitlines()
        latest = collect_latest(lines, args.pipelines)
    else:
        latest = {}

    snapshot = build_snapshot(latest, args.pipelines)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
