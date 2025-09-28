"""Pipeline status tracking with MinIO storage."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Dict
from typing import Iterable
from typing import Optional

from croniter import croniter

from ai_tools_website.v1.data_manager import get_minio_client

SUMMARY_PREFIX = "PIPELINE_SUMMARY"
DEFAULT_PIPELINES = ["discovery", "maintenance", "enhancement"]
STALE_THRESHOLD = timedelta(hours=6)
PIPELINE_STATUS_KEY = "pipeline_status.json"

logger = logging.getLogger(__name__)


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


def calculate_next_run(cron_expression: str) -> Optional[Dict[str, str]]:
    """Calculate next run time from cron expression."""
    try:
        now = datetime.now(timezone.utc)
        cron = croniter(cron_expression, now)
        next_run = cron.get_next(datetime)

        # Calculate time until next run
        time_until = next_run - now
        days = time_until.days
        hours, remainder = divmod(time_until.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            time_until_str = f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            time_until_str = f"{hours}h {minutes}m"
        else:
            time_until_str = f"{minutes}m"

        return {"next_run": next_run.isoformat(), "next_run_in": time_until_str}
    except Exception as e:
        logger.warning(f"Failed to calculate next run for cron '{cron_expression}': {e}")
        return None


def get_cron_schedules() -> Dict[str, str]:
    """Get cron schedules for each pipeline."""
    # These should match the actual crontab entries
    return {
        "discovery": "0 2 * * *",  # Daily at 2 AM UTC
        "enhancement": "0 3 * * 1",  # Weekly on Monday at 3 AM UTC
    }


def build_snapshot(latest: Dict[str, Dict], pipelines: Iterable[str]) -> Dict:
    """Build status snapshot with next run information."""
    now = datetime.now(timezone.utc)
    cron_schedules = get_cron_schedules()

    snapshot = {
        "generated_at": now.isoformat(),
        "pipelines": [],
    }

    for pipeline in pipelines:
        entry = latest.get(pipeline)

        # Handle maintenance special case - it runs automatically after discovery
        if pipeline == "maintenance":
            discovery_entry = latest.get("discovery")
            if discovery_entry and discovery_entry.get("status") == "success":
                # Maintenance ran as part of discovery
                snapshot["pipelines"].append(
                    {
                        "pipeline": pipeline,
                        "status": "success",
                        "started_at": discovery_entry.get("started_at"),
                        "finished_at": discovery_entry.get("finished_at"),
                        "duration_seconds": discovery_entry.get("duration_seconds"),
                        "schedule": "auto_after_discovery",
                        "next_run": "after_discovery_completes",
                        "next_run_in": "follows discovery",
                        "metrics": {"note": "Runs automatically after discovery pipeline"},
                        "attributes": {"triggered_by": "discovery"},
                    }
                )
            else:
                snapshot["pipelines"].append(
                    {
                        "pipeline": pipeline,
                        "status": "pending",
                        "schedule": "auto_after_discovery",
                        "next_run": "after_next_discovery",
                        "next_run_in": "follows discovery",
                    }
                )
            continue

        if not entry:
            # Calculate next run for missing pipelines
            cron_expr = cron_schedules.get(pipeline)
            next_run_info = calculate_next_run(cron_expr) if cron_expr else {}

            snapshot["pipelines"].append(
                {"pipeline": pipeline, "status": "missing", "schedule": cron_expr or "unknown", **next_run_info}
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

        # Add schedule and next run information
        cron_expr = cron_schedules.get(pipeline)
        next_run_info = calculate_next_run(cron_expr) if cron_expr else {}

        pipeline_data = {
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
            "schedule": cron_expr or "unknown",
            **next_run_info,
        }

        snapshot["pipelines"].append(pipeline_data)

    return snapshot


def update_pipeline_status(log_file_path: Path = Path("logs/ai_tools.log"), pipelines: list[str] = None) -> None:
    """Update pipeline status and upload to MinIO."""
    if pipelines is None:
        pipelines = DEFAULT_PIPELINES

    # Read log file if it exists
    if log_file_path.exists():
        lines = log_file_path.read_text().splitlines()
        latest = collect_latest(lines, pipelines)
    else:
        logger.warning(f"Log file not found: {log_file_path}")
        latest = {}

    # Build snapshot
    snapshot = build_snapshot(latest, pipelines)

    # Upload to MinIO
    minio_client = get_minio_client()
    bucket_name = "ai-tools"  # Same bucket as tools.json

    # Convert to JSON bytes
    json_data = json.dumps(snapshot, indent=2).encode("utf-8")

    # Upload to MinIO
    from io import BytesIO

    minio_client.put_object(
        bucket_name,
        PIPELINE_STATUS_KEY,
        BytesIO(json_data),
        len(json_data),
        content_type="application/json",
    )

    logger.info(f"Pipeline status updated in MinIO: {PIPELINE_STATUS_KEY}")


def load_pipeline_status() -> Dict:
    """Load pipeline status from MinIO."""
    minio_client = get_minio_client()
    bucket_name = "ai-tools"

    response = minio_client.get_object(bucket_name, PIPELINE_STATUS_KEY)
    data = json.loads(response.read().decode("utf-8"))
    logger.debug("Loaded pipeline status from MinIO")
    return data
